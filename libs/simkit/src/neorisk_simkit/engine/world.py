"""World state: the hidden-array table and its allocation, and `World` — everything one run
holds in memory (read tables, owner/shard state, queues, slabs) plus the partition executor.

`World.run_slots` drives the generated `run_partitions` (see `engine.codegen` for the world tuple
`W` it receives) and handles the statuses it returns: `NEED_SWAP` flushes a full record/create
slab into `World.chunks[worker]` or moves a full outbox aside into `World.pending_outbox[worker]`,
`NEED_NODES` refills the worker's command-node free list from the reserve.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
from numba import njit

from neorisk_simkit.engine import rng
from neorisk_simkit.engine.abi import PRIO_MESSAGE, START
from neorisk_simkit.engine.calendar import Calendar
from neorisk_simkit.engine.cmdq import PAYLOAD_W, NodePool, PayloadPool, q_push
from neorisk_simkit.engine.codegen import (
    COUNTERS,
    DONE,
    NEED_NODES,
    NEED_SWAP,
    WORLD_FIELDS,
)
from neorisk_simkit.engine.errors import CapExceeded, EngineError
from neorisk_simkit.engine.layout import _recipes as layout_recipes
from neorisk_simkit.engine.slabs import SlabSet, StepChunk, slab_dtype
from neorisk_simkit.spec import dist as _dist
from neorisk_simkit.spec.dist import Dist

# (name, numpy dtype name, per-slot multiplicity: 1, "A" = max processes per partition type,
# "N_NS" = number of id namespaces). The cap formula and the allocation both read this table.
HIDDEN_DTYPES: tuple[tuple[str, str, int | str], ...] = (
    ("pid", "int64", 1),
    ("ptype", "int16", 1),
    ("lslot", "int32", 1),
    ("gen", "uint32", 1),
    ("alive", "uint8", 1),
    ("clock", "int64", 1),
    ("rseq", "int32", 1),
    ("cseq", "int64", 1),
    ("pending", "int32", 1),
    ("qhead", "int32", 1),
    ("inst", "int64", 1),
    ("self_id", "int64", 1),
    ("occ", "uint32", "A"),
    ("ordn", "int32", "N_NS"),
    ("retire_at", "int64", 1),
    ("susp_t", "int64", 1),
    ("susp_delta", "int64", 1),
)


def hidden_bytes(a: int, n_ns: int) -> int:
    """Bytes of hidden partition arrays per global slot."""
    mult = {"A": a, "N_NS": n_ns}
    return sum(np.dtype(dt).itemsize * (m if isinstance(m, int) else mult[m])
               for _, dt, m in HIDDEN_DTYPES)


# Fill value per hidden array; every other array starts at 0.
_I64_MAX = int(np.iinfo(np.int64).max)
_FILL = {"qhead": -1, "retire_at": _I64_MAX, "susp_t": _I64_MAX}


class Hidden:
    """Engine-owned per-slot arrays, one attribute per `HIDDEN_DTYPES` row (length G)."""

    def __init__(self, arrays: dict[str, np.ndarray]):
        for name, _, _ in HIDDEN_DTYPES:
            setattr(self, name, arrays[name])


def hidden_dims(plan: Any) -> dict[str, int]:
    """Resolved multiplicities: A = max processes per partition type, N_NS = id namespaces."""
    per_type: dict[str, int] = {}
    for p in plan.processes:
        per_type[p.partition] = per_type.get(p.partition, 0) + 1
    return {"A": max(1, max(per_type.values(), default=1)), "N_NS": len(plan.namespaces)}


def allocate_hidden(plan: Any, run: Any = None) -> tuple[Hidden, dict[str, int]]:
    """Allocate every hidden array for G = sum(owner max_live) + sum(shard n) global slots.

    Owner slot ranges come first in plan order, then shards; returns `slot_base` per type.
    """
    slot_base: dict[str, int] = {}
    g = 0
    for kind in ("owner", "shard"):
        for part in plan.partitions:
            if part.kind == kind:
                slot_base[part.name] = g
                g += part.max_live if kind == "owner" else part.n
    dims = hidden_dims(plan)
    arrays = {}
    for name, dt, mult in HIDDEN_DTYPES:
        shape = (g,) if mult == 1 else (g, mult if isinstance(mult, int) else dims[mult])
        arrays[name] = np.full(shape, _FILL.get(name, 0), np.dtype(dt))
    return Hidden(arrays), slot_base


# ---------------------------------------------------------------------------- World
NODE_CHUNK = 256                      # command nodes moved from the reserve per worker refill
_DAY_US = 86_400_000_000
_NULL = int(np.iinfo(np.int64).min)
_NP = {"i8": "int8", "i16": "int16", "i32": "int32", "i64": "int64", "u8": "uint8",
       "u32": "uint32", "f64": "float64", "ref": "int64"}


@njit(cache=True, nogil=True)
def _mix_tail(h, ords, out):
    """out[i] = mix64(h ^ ords[i]): the last step of `rng.mix(..., ordinal)`."""
    for i in range(ords.shape[0]):
        out[i] = rng.mix64(rng.u64(h) ^ rng.u64(ords[i]))


@njit(cache=True, nogil=True)
def _queue_starts(P, qhead, cseq, gs, times, procs, prio):
    """Queue one START per (slot, process); P's free list is the pool's reserve list."""
    for i in range(gs.shape[0]):
        g = gs[i]
        for a in procs:
            sq = cseq[g]
            cseq[g] = sq + 1
            if q_push(P, 0, qhead, g, times[i], prio, 0, sq, START, a, 0, -1) < 0:
                return False
    return True


def instance_keys(name: str, ordinals: np.ndarray) -> np.ndarray:
    """`rng.mix(name_key(name), ordinal)` per ordinal, as int64 (the hidden `inst` values)."""
    out = np.empty(len(ordinals), np.uint64)
    _mix_tail(np.uint64(rng.mix(rng.name_key(name))), np.asarray(ordinals, np.int64), out)
    return out.view(np.int64)


def _fill_value(dtype: np.dtype) -> Any:
    """`std.NULL` for int64; the dtype's minimum (or NaN) where NULL does not fit."""
    if dtype == np.int64:
        return _NULL
    return np.nan if dtype.kind == "f" else np.iinfo(dtype).min


def flatten_config(cfg: Any) -> tuple:
    """A process config as the kernel `cfg` tuple: fields in order, nested dataclasses as nested
    tuples, `Dist` as `(code, p1, p2, p3)`."""
    def flat(v: Any) -> Any:
        if isinstance(v, Dist):
            code, p1, p2, p3 = _dist.encode(v)
            return (int(code), float(p1), float(p2), float(p3))
        if dataclasses.is_dataclass(v) and not isinstance(v, type):
            return tuple(flat(getattr(v, f.name)) for f in dataclasses.fields(v))
        if isinstance(v, (tuple, list)):
            return tuple(flat(x) for x in v)
        return v
    return () if cfg is None else flat(cfg)


def arrival_times(d: Dist | None, u: np.ndarray, t0: int, t1: int) -> np.ndarray:
    """Arrival time per uniform over `[t0, t1)` by inverse cdf of a per-UTC-day density.

    `poisson_daily(weekly, trend)`: day k of the window (k = 0 for the day holding t0) has
    density proportional to `weekly[weekday] * (1 + trend) ** k` (weekday 0 = Monday); `None`
    is a flat density.
    """
    if len(u) == 0:
        return np.zeros(0, np.int64)
    if t1 <= t0:
        raise EngineError("population arrivals need a non-empty simulated window")
    first = (t0 // _DAY_US + 1) * _DAY_US
    edges = np.array([t0, *range(first, t1, _DAY_US), t1], np.int64)
    lengths = np.diff(edges).astype(np.float64)
    weights = lengths.copy()
    if d is not None:
        if d.kind != _dist.POISSON_DAILY:
            raise EngineError("population arrivals must be dist.poisson_daily(...)")
        days = edges[:-1] // _DAY_US
        weekday = (days + 3) % 7                     # 1970-01-01 was a Thursday
        weights *= np.asarray(d.weights, np.float64)[weekday]
        weights *= (1.0 + d.params[0]) ** (days - days[0]).astype(np.float64)
    cum = np.concatenate([[0.0], np.cumsum(weights)])
    if not cum[-1] > 0:
        raise EngineError("population arrivals have zero weight over the simulated window")
    x = u * cum[-1]
    b = np.clip(np.searchsorted(cum, x, side="right") - 1, 0, len(weights) - 1)
    frac = np.clip((x - cum[b]) / np.where(weights[b] > 0, weights[b], 1.0), 0.0, 1.0)
    t = edges[b] + np.floor(frac * lengths[b]).astype(np.int64)
    return np.minimum(t, edges[b + 1] - 1)


@dataclasses.dataclass
class _Population:
    table: str
    part: Any                                  # owner PartitionDef
    times: np.ndarray                          # admission time per ordinal (ascending)
    attrs: dict[str, np.ndarray]               # column -> value per ordinal
    procs: np.ndarray                          # actions started by on_created(table)
    next: int = 0                              # first ordinal not yet admitted


class World:
    """Everything one run holds in memory, plus the partition executor (`run_slots`)."""

    # ------------------------------------------------------------------ build
    @classmethod
    def build(cls, run: Any, *, threads: int, checked: bool = False) -> World:
        from neorisk_simkit.engine.build import build_engine  # build -> codegen -> world

        self = cls()
        plan, eng = run.plan, run.engine
        self.run, self.plan, self.checked = run, plan, checked
        self.threads = int(threads)
        self.seed = int(run.seed)
        self.sim_start = int(run.start_us - run.warmup_us)
        self.sim_end = int(run.start_us + run.span_us)
        self.eng = build_engine(plan, checked=checked)
        self.hidden, self.slot_base = allocate_hidden(plan, run)
        self.G = len(self.hidden.pid)
        self.pool = NodePool(eng.timer_nodes, self.threads)
        self.payload = PayloadPool(eng.payload_slots, self.threads)
        self._build_tables()
        self._build_owners()
        self._build_shards()
        self._build_populations()
        self._build_world_tuple()
        horizon = max(1, self.sim_end - self.sim_start)
        width = max(1, eng.step_min_us)
        self.calendar = Calendar(self.G, self.sim_start, width, horizon // width + 2,
                                 2 * self.G + 64, checked=checked)
        self.slabs = [SlabSet(plan, eng, w) for w in range(self.threads)]
        self._outs = [s.as_tuple(self.hidden, self.pool, self.payload, self.seed)
                      for s in self.slabs]
        self.chunks: list[list[StepChunk]] = [[] for _ in range(self.threads)]
        self.pending_outbox: list[list[dict[str, np.ndarray]]] = [
            [] for _ in range(self.threads)]
        return self

    def _recipes(self) -> list[Any]:
        return layout_recipes(self.plan)

    def _build_tables(self) -> None:
        """Rows of every read-only table: from its source, or from the recipe that builds it."""
        plan = self.plan
        self.tables: dict[str, dict[str, np.ndarray]] = {}
        self.cumw: dict[str, np.ndarray] = {}
        for t in plan.tables:
            rows = None
            if t.source is not None:
                stream = rng.name_key(t.name)
                rows = t.source.generate(t.source.n, t, self.seed, stream)
                weight = getattr(t.source, "weight", None)
                if weight is not None:
                    self.cumw[t.name] = self._cumw(weight, t.source.n, stream)
            else:
                for r in self._recipes():
                    built = r.table_rows(t.name) if hasattr(r, "table_rows") else None
                    if built is not None:
                        rows = built
                        break
            if rows is not None:
                self.tables[t.name] = {c.name: np.asarray(rows[c.name], slab_dtype(c))
                                       for c in t.cols}

    def _cumw(self, weight: Dist, n: int, stream: int) -> np.ndarray:
        """Normalised cumulative weight ending at exactly 1.0 (for `sample_by_weight`)."""
        s = rng.mix(stream, rng.name_key("weight"))
        w = _dist.sample_np(weight, rng.uniforms(self.seed, s, n),
                            rng.uniforms(self.seed, s, n, offset=n)).astype(np.float64)
        cum = np.cumsum(w)
        if n == 0 or not cum[-1] > 0:
            raise EngineError("source weights must have a positive sum")
        cum /= cum[-1]
        cum[-1] = 1.0
        return cum

    def _build_owners(self) -> None:
        """State arrays per owner type (max_live rows) and local arrays per process."""
        plan, hid = self.plan, self.hidden
        self.state: dict[str, tuple[np.ndarray, ...]] = {}
        self.state_init: dict[str, list[Any]] = {}
        self.free_lslots: dict[str, np.ndarray] = {}
        for part in plan.partitions:
            if part.kind != "owner":
                continue
            cols = plan.table(part.table).cols
            dts = [slab_dtype(c) for c in cols]
            init = [_fill_value(dt) if (c.ltype.kind == "ref" or c.ltype.nullable) else 0
                    for c, dt in zip(cols, dts, strict=True)]
            self.state[part.name] = tuple(np.full(part.max_live, v, dt)
                                          for v, dt in zip(init, dts, strict=True))
            self.state_init[part.name] = init
            self.free_lslots[part.name] = np.arange(part.max_live, dtype=np.int32)
            base = self.slot_base[part.name]
            hid.ptype[base:base + part.max_live] = part.ptype_code
            hid.lslot[base:base + part.max_live] = np.arange(part.max_live)
        self.locals: dict[str, tuple[np.ndarray, ...]] = {}
        for p in plan.processes:
            if p.kernel.local is None:
                continue
            rows = plan.partition(p.partition).max_live
            arrs = []
            for kind, width in p.kernel.local.fields.values():
                dt = np.dtype(_NP[kind])
                shape = (rows,) if width == 1 else (rows, width)
                arrs.append(np.full(shape, _fill_value(dt) if kind == "ref" else 0, dt))
            self.locals[p.name] = tuple(arrs)

    def _build_shards(self) -> None:
        """Shard slots, items CSR by the shard key column, and initial shard state."""
        plan, hid = self.plan, self.hidden
        self.offs: dict[str, np.ndarray] = {}
        self.items: dict[str, np.ndarray] = {}
        self.local_index: dict[str, np.ndarray] = {}
        for part in plan.partitions:
            if part.kind != "shard":
                continue
            n = part.n
            if part.items is not None:
                keys = np.asarray(self.tables[part.items][part.key], np.int64)
                if len(keys) and (keys.min() < 0 or keys.max() >= n):
                    raise EngineError(f"shard {part.name}: items column {part.key} must lie in "
                                      f"[0, {n})")
                order = np.argsort(keys, kind="stable").astype(np.int64)
                offs = np.zeros(n + 1, np.int64)
                offs[1:] = np.cumsum(np.bincount(keys, minlength=n))
                li = np.empty(len(keys), np.int64)
                li[order] = np.arange(len(keys)) - offs[keys[order]]
                self.local_index[part.items] = li
            else:
                order, offs = np.zeros(0, np.int64), np.zeros(n + 1, np.int64)
            self.offs[part.name], self.items[part.name] = offs, order
            self.state[part.name] = self._shard_state(part, order)
            base = self.slot_base[part.name]
            idx = np.arange(n, dtype=np.int64)
            g = slice(base, base + n)
            hid.ptype[g] = part.ptype_code
            hid.lslot[g] = idx
            hid.pid[g] = (part.ptype_code << 56) | idx
            hid.alive[g] = 1
            hid.self_id[g] = idx
            hid.inst[g] = instance_keys(part.name, idx)

    def _shard_state(self, part: Any, order: np.ndarray) -> tuple[np.ndarray, ...]:
        """State arrays: per-item fields in CSR order (length = items), scalars per shard."""
        from neorisk_simkit.engine.layout import _STATE_RE

        init = part.init
        recipe_vals = None
        if init is not None and not isinstance(init, dict) and hasattr(init, "init"):
            stream = rng.name_key(part.name)
            recipe_vals = init.init(n_items=len(order), n_shards=part.n, seed=self.seed,
                                    stream=stream)
        arrays = []
        for field, decl in part.state.items():
            m = _STATE_RE.match(decl)
            dt = np.dtype(_NP[m.group(1)])
            per_item = m.group(2) is not None
            size = len(order) if per_item else part.n
            v = recipe_vals.get(field) if recipe_vals is not None else (
                init.get(field) if isinstance(init, dict) else None)
            if v is None:
                arrays.append(np.zeros(size, dt))
                continue
            if isinstance(v, Dist):
                s = rng.mix(rng.name_key(part.name), rng.name_key(field))
                v = _dist.sample_np(v, rng.uniforms(self.seed, s, size),
                                    rng.uniforms(self.seed, s, size, offset=size))
            v = np.asarray(v)
            if len(v) != size:
                raise EngineError(f"shard {part.name}: init of {field} has {len(v)} values, "
                                  f"expected {size}")
            arrays.append((v[order] if per_item else v).astype(dt))   # item-row -> CSR order
        return tuple(arrays)

    def _build_populations(self) -> None:
        plan = self.plan
        self.populations: list[_Population] = []
        owner_of = {p.table: p for p in plan.partitions if p.kind == "owner"}
        for pop in plan.populations:
            part = owner_of[pop.table]
            n_init = int(np.floor(pop.n * pop.initial + 0.5))
            n_arr = pop.n - n_init
            s = rng.mix(rng.name_key(pop.table), rng.name_key("arrivals"))
            arr = arrival_times(pop.arrivals, rng.uniforms(self.seed, s, n_arr),
                                self.sim_start, self.sim_end)
            # ordinal = rank by (arrival time, draw index); initial owners come first at t0
            times = np.concatenate([np.full(n_init, self.sim_start, np.int64),
                                    np.sort(arr, kind="stable")])
            table = plan.table(pop.table)
            dts = {c.name: slab_dtype(c) for c in table.cols}
            attrs = {}
            for col, d in pop.attrs.items():
                s = rng.mix(rng.name_key(pop.table), rng.name_key("attr"), rng.name_key(col))
                attrs[col] = _dist.sample_np(
                    d, rng.uniforms(self.seed, s, pop.n),
                    rng.uniforms(self.seed, s, pop.n, offset=pop.n)).astype(dts[col])
            procs = np.array([p.action_id for p in plan.processes
                              if p.partition == part.name and p.start is not None
                              and p.start.table == pop.table], np.int64)
            self.populations.append(_Population(pop.table, part, times, attrs, procs))

    def _refs_csr(self, name: str) -> tuple[np.ndarray, np.ndarray]:
        for pop in self.plan.populations:
            if name in pop.refs:
                offs, idx = pop.refs[name].csr()
                return np.asarray(offs, np.int64), np.asarray(idx, np.int64)
        raise EngineError(f"no population declares refs {name!r}")

    def _build_world_tuple(self) -> None:
        plan, hid = self.plan, self.hidden
        recipes = self._recipes()
        item_tables = {p.items for p in plan.partitions if p.items is not None}
        ws, cfgs, reads, refs = [], [], [], []
        occ_col = np.zeros(len(plan.processes), np.int64)
        seen: dict[str, int] = {}
        every = np.zeros(len(plan.processes), np.int64)
        jitter = np.zeros((len(plan.processes), 4), np.float64)
        jitter[:, 0] = -1.0
        for p in plan.processes:
            part = plan.partition(p.partition)
            occ_col[p.action_id] = seen.get(part.name, 0)
            seen[part.name] = occ_col[p.action_id] + 1
            entry: tuple = ((hid.lslot, self.state[part.name]) if part.kind == "owner" else
                            (hid.lslot, self.offs[part.name], self.items[part.name],
                             self.state[part.name]))
            if p.kernel.local is not None:
                entry = (*entry, self.locals[p.name])
            ws.append(entry)
            cfgs.append(flatten_config(p.config))
            arrs: list[np.ndarray] = []
            for tname in p.reads.values():
                t = plan.table(tname)
                if tname not in self.tables:
                    raise EngineError(f"process {p.name} reads {tname}, which has no rows")
                arrs += [self.tables[tname][c.name] for c in t.cols]
                for r in recipes:
                    extra = r.extra_read_columns(tname) if r.read_column_names(tname) else {}
                    arrs += [np.asarray(extra[c]) for c in r.read_column_names(tname)]
                if tname in item_tables:
                    arrs.append(self.local_index[tname])
                if tname in self.cumw:
                    arrs.append(self.cumw[tname])
            reads.append(tuple(arrs))
            pairs: list[np.ndarray] = []
            for name in p.refs.values():
                pairs += list(self._refs_csr(name))
            refs.append(tuple(pairs))
            if p.every_us is not None:
                every[p.action_id] = p.every_us
                if p.jitter is not None:
                    jitter[p.action_id] = _dist.encode(p.jitter)
        retire = np.zeros(32, np.uint8)
        for part in plan.partitions:
            retire[part.ptype_code] = 1 if part.retire_when_idle else 0
        self.world_state = tuple(ws)
        self.action_args = (tuple(cfgs), tuple(reads), tuple(refs))
        self.counters = np.zeros((self.threads, len(COUNTERS)), np.int64)
        self.rejects = np.zeros((self.threads, len(plan.processes)), np.int64)
        self.kc = np.zeros((self.threads, 33), np.int64)
        parts = {
            "hid": tuple(getattr(hid, n) for n, _, _ in HIDDEN_DTYPES),
            "pool": self.pool.as_tuple(), "pay": self.payload.as_tuple(),
            "state": self.world_state, "args": self.action_args, "seed": self.seed,
            "counters": self.counters, "rejects": self.rejects, "occ_col": occ_col,
            "retire": retire, "every": every, "jitter": jitter, "sim_start": self.sim_start,
            "kc": self.kc, "nopay": np.zeros((1, PAYLOAD_W), np.int64)}
        self._W = tuple(parts[f] for f in WORLD_FIELDS)

    # ------------------------------------------------------------------ admission
    def _reserve_pool(self) -> tuple:
        """The node pool tuple with the reserve list in place of the worker free lists."""
        return self.pool.as_tuple()[:8] + (self.pool.reserve_head, self.pool.reserve_n)

    def _take_reserve_nodes(self, need: int) -> None:
        """Ensure the reserve holds `need` nodes (called between phases, never concurrently)."""
        if self.pool.reserve_n[0] < need:
            self.pool.splice_all()
        if self.pool.reserve_n[0] < need:
            raise CapExceeded("timer_heaps", self.pool.capacity, self.pool.in_use() + need)

    def admit_population(self, t0: int, t1: int) -> np.ndarray:
        """Admit every population owner arriving in `[t0, t1)`; returns their global slots.

        Each admitted owner gets a slot, its initial state (attrs) and one `START` command at
        its arrival time (`PRIO_MESSAGE`) per process started by `on_created(table)`.
        """
        hid = self.hidden
        admitted = []
        for pop in self.populations:
            lo = int(np.searchsorted(pop.times, t0, side="left"))
            hi = int(np.searchsorted(pop.times, t1, side="left"))
            if lo > pop.next:
                raise EngineError(f"population {pop.table}: admission window starts at {t0}, "
                                  f"but arrivals from {int(pop.times[pop.next])} were skipped")
            lo = max(lo, pop.next)
            k = hi - lo
            if k <= 0:
                continue
            part = pop.part
            free = self.free_lslots[part.name]
            if k > len(free):
                live = part.max_live - len(free)
                raise CapExceeded("live_partition_state", part.max_live, live + k)
            lslots, self.free_lslots[part.name] = free[:k], free[k:]
            ords = np.arange(lo, hi, dtype=np.int64)
            g = self.slot_base[part.name] + lslots.astype(np.int64)
            hid.pid[g] = (part.ptype_code << 56) | ords
            hid.alive[g] = 1
            for name in ("clock", "rseq", "cseq", "pending", "susp_delta"):
                getattr(hid, name)[g] = 0
            hid.occ[g] = 0
            hid.ordn[g] = 0
            hid.retire_at[g] = _I64_MAX
            hid.susp_t[g] = _I64_MAX
            hid.inst[g] = instance_keys(pop.table, ords)
            hid.self_id[g] = ords
            cols = self.plan.table(pop.table).cols
            for c, arr, v in zip(cols, self.state[part.name], self.state_init[part.name],
                                 strict=True):
                arr[lslots] = pop.attrs[c.name][ords] if c.name in pop.attrs else v
            for p in self.plan.processes:
                if p.partition == part.name and p.kernel.local is not None:
                    for (kind, _), arr in zip(p.kernel.local.fields.values(), self.locals[p.name],
                                              strict=True):
                        arr[lslots] = _fill_value(arr.dtype) if kind == "ref" else 0
            self._take_reserve_nodes(k * len(pop.procs))
            ok = _queue_starts(self._reserve_pool(), hid.qhead, hid.cseq, g, pop.times[lo:hi],
                               pop.procs, PRIO_MESSAGE)
            assert ok, "reserve nodes were checked above"
            pop.next = hi
            admitted.append(g)
        return np.concatenate(admitted) if admitted else np.zeros(0, np.int64)

    def init_shards(self) -> None:
        """Queue occurrence 0 of every periodic shard process (D26)."""
        hid = self.hidden
        W = self._W
        every, jitter = W[WORLD_FIELDS.index("every")], W[WORLD_FIELDS.index("jitter")]
        for p in self.plan.processes:
            part = self.plan.partition(p.partition)
            if p.every_us is None or part.kind != "shard":
                continue
            a = p.action_id
            self._take_reserve_nodes(part.n)
            g = self.slot_base[part.name] + np.arange(part.n, dtype=np.int64)
            times = np.array([self.eng.periodic_time(self.seed, hid.inst[x], a, 0, every[a],
                                                     jitter[a], self.sim_start) for x in g],
                             np.int64)
            ok = _queue_starts(self._reserve_pool(), hid.qhead, hid.cseq, g, times,
                               np.array([a], np.int64), PRIO_MESSAGE)
            assert ok, "reserve nodes were checked above"

    # ------------------------------------------------------------------ execution
    def run_slots(self, worker: int, slots: np.ndarray, limit_t: int, *, owners: bool) -> None:
        """Run each slot's commands with time < `limit_t` (owners stop at a suspending commit)."""
        slots = np.ascontiguousarray(slots, np.int64)
        out, slab = self._outs[worker], self.slabs[worker]
        i = 0
        while True:
            status, i = self.eng.run_partitions(self._W, out, worker, slots, i, int(limit_t),
                                                bool(owners))
            if status == DONE:
                return
            if status == NEED_SWAP:
                m = int(slab.miss[0])
                if m >= 0 and slab.resources[m] == "requests":
                    self.pending_outbox[worker].append(slab.outbox_view())
                    slab.reset_outbox()
                else:
                    self._flush(worker)
            elif status == NEED_NODES:
                self._refill_nodes(worker)
            else:
                raise EngineError(f"run_partitions returned unknown status {status}")

    def _refill_nodes(self, worker: int) -> None:
        pool = self.pool
        force = self.run.engine.force_capacity.get("timers")
        chunk = NODE_CHUNK if force is None else int(force) - int(pool.free_n[worker])
        if pool.reserve_n[0] == 0:
            raise CapExceeded("timer_heaps", pool.capacity, pool.in_use() + 1)
        chunk = min(chunk, int(pool.reserve_n[0]))
        if chunk > 0:                  # else a forced list is full: the retry cap ends the run
            pool.refill(worker, chunk)

    def _flush(self, worker: int) -> None:
        chunk = self.slabs[worker].flush()
        if any(len(v["time"]) for v in chunk.records.values()) or any(
                len(v["handle"]) for v in chunk.creates.values()):
            self.chunks[worker].append(chunk)

    def flush_all(self) -> None:
        """Flush every worker slab into its `chunks` list."""
        for w in range(self.threads):
            self._flush(w)

    def take_chunks(self) -> list[StepChunk]:
        """Return and clear every flushed chunk (all workers)."""
        out = [c for chunks in self.chunks for c in chunks]
        for chunks in self.chunks:
            chunks.clear()
        return out

    @property
    def stats(self) -> dict[str, Any]:
        c = self.counters.sum(axis=0)
        rej = self.rejects.sum(axis=0)
        return {"rejects": {p.name: int(rej[p.action_id]) for p in self.plan.processes},
                "retries": int(c[COUNTERS.index("retries")]),
                "late_messages": int(c[COUNTERS.index("late_messages")]),
                "continuations": int(c[COUNTERS.index("continuations")])}
