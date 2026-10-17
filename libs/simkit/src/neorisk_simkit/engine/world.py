"""World state: the hidden-array table and its allocation, and `World` — everything one run
holds in memory (read tables, owner/shard state, queues, slabs) plus the partition executor.

`World.run_slots` drives the generated `run_partitions` (see `engine.codegen` for the world tuple
`W` it receives) and handles the statuses it returns: `NEED_SWAP` flushes a full record/create
slab into `World.chunks[worker]` or moves a full outbox aside into `World.pending_outbox[worker]`,
`NEED_NODES` refills the worker's command-node free list from the reserve.

Between phases `World` routes outboxes (`route`, over `engine.route`), admits created owners
(`admit_created`) and keeps the per-step bookkeeping the round loop (`engine.rounds`) needs:
the touched slots, the calendar of owners' next command times and the message budget.
"""

from __future__ import annotations

import dataclasses
import threading
from typing import Any

import numpy as np
from numba import njit

from neorisk_simkit.engine import rng
from neorisk_simkit.engine import route as rt
from neorisk_simkit.engine.abi import PRIO_MESSAGE, START
from neorisk_simkit.engine.calendar import Calendar, cal_collect, cal_push
from neorisk_simkit.engine.cmdq import PAYLOAD_W, NodePool, PayloadPool, q_push
from neorisk_simkit.engine.codegen import (
    COUNTERS,
    DONE,
    NEED_NODES,
    NEED_SWAP,
    WORLD_FIELDS,
)
from neorisk_simkit.engine.errors import CapExceeded, EngineError
from neorisk_simkit.engine.identity import handle_ordinal
from neorisk_simkit.engine.layout import _recipes as layout_recipes
from neorisk_simkit.engine.slabs import OB_CREATE, OUTBOX_COLS, SlabSet, StepChunk, slab_dtype
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
    ("last_t", "int64", 1),        # time of the last executed command (monotonic-time guard)
)


def hidden_bytes(a: int, n_ns: int) -> int:
    """Bytes of hidden partition arrays per global slot."""
    mult = {"A": a, "N_NS": n_ns}
    return sum(np.dtype(dt).itemsize * (m if isinstance(m, int) else mult[m])
               for _, dt, m in HIDDEN_DTYPES)


# Fill value per hidden array; every other array starts at 0.
_I64_MAX = int(np.iinfo(np.int64).max)
_FILL = {"qhead": -1, "retire_at": _I64_MAX, "susp_t": _I64_MAX,
         "last_t": int(np.iinfo(np.int64).min)}


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


@njit(cache=True, nogil=True)
def _cal_push_all(C, gs, ts, start):
    """Push (gs[i], ts[i]) from `start` on; the index of the first push that found no room."""
    for i in range(start, gs.shape[0]):
        if not cal_push(C, gs[i], ts[i]):
            return i
    return gs.shape[0]


def _as_i64(v: int) -> int:
    """An unsigned 64-bit key as the int64 stored in hidden arrays."""
    return int(np.array([v & rng.MASK64], np.uint64).view(np.int64)[0])


@dataclasses.dataclass(frozen=True)
class _Creation:
    """An `OB_CREATE` outbox row waiting for admission (sorted by the routing key)."""
    time: int
    prio: int
    cause: int                                 # the creator's commit lamport
    src_pid: int
    src_seq: int
    ns: int                                    # namespace code of the created table
    handle: int                                # provisional handle of the created row
    src_g: int                                 # creator's global slot
    action: int                                # creator's process (action id)


class _CreatedIndex:
    """`handle -> created row` over one step's create slabs and flushed chunks, for one namespace,
    built incrementally (see `World._created_rows`)."""

    def __init__(self, ns: str) -> None:
        self.ns = ns
        self.rows: dict[int, tuple[dict[str, np.ndarray], int]] = {}
        self.seen: dict[int, tuple[int, int]] = {}  # worker -> (chunks indexed, live rows indexed)

    def add(self, cols: dict[str, np.ndarray], lo: int, hi: int) -> int:
        for i, h in enumerate(cols["handle"][lo:hi].tolist(), lo):
            self.rows[h] = (cols, i)
        return max(0, hi - lo)

    def __call__(self, handle: int) -> dict[str, Any]:
        got = self.rows.get(handle)
        if got is None:
            raise EngineError(f"created row {handle} of {self.ns} is missing from the create "
                              "slabs")
        cols, i = got
        return {k: v[i] for k, v in cols.items()}


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

    def allocated_slab_bytes(self) -> int:
        """Sum of `nbytes` of every output buffer of every worker's `SlabSet`."""
        total = 0
        for slab in self.slabs:
            total += sum(a.nbytes for cols in slab.buffers.values() for a in cols.values())
            total += sum(a.nbytes for a in slab.outbox.values()) + slab.outbox_pay.nbytes
        return total

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
        self._reserve_lock = threading.Lock()     # workers refill from one reserve list
        self.payload = PayloadPool(eng.payload_slots, self.threads)
        self._build_populations()
        self._build_recipes()
        self._build_tables()
        self._build_owners()
        self._build_shards()
        self._build_world_tuple()
        horizon = max(1, self.sim_end - self.sim_start)
        width = max(1, eng.step_min_us)
        self.calendar = Calendar(self.G, self.sim_start, width, horizon // width + 2,
                                 2 * self.G + 64, checked=checked)
        self.slabs = [SlabSet(plan, eng, w) for w in range(self.threads)]
        self._outs = [s.as_tuple(self.hidden, self.pool, self.payload, self.seed)
                      for s in self.slabs]
        self.chunks: list[list[StepChunk]] = [[] for _ in range(self.threads)]
        self._created_index: dict[str, _CreatedIndex] = {}  # this step's, by namespace
        self.created_rows_indexed = 0               # rows indexed for admission (whole run)
        self._step_lock = threading.Lock()
        self.step_rows = 0                          # rows / bytes flushed this step (all
        self.step_bytes = 0                         # record and create buffers, ids included)
        self.pending_outbox: list[list[dict[str, np.ndarray]]] = [
            [] for _ in range(self.threads)]
        self._build_route()
        return self

    def _recipes(self) -> list[Any]:
        return layout_recipes(self.plan)

    def _build_recipes(self) -> None:
        """Generate every population-refs recipe (the recipe protocol of `std.sources`): the
        rows of the tables it builds and its owner CSR, keyed by population and refs name."""
        times = {pop.table: pop.times for pop in self.populations}
        for pop in self.plan.populations:
            for name, r in pop.refs.items():
                if hasattr(r, "generate"):
                    stream = rng.mix(rng.name_key(pop.table), rng.name_key("refs"),
                                     rng.name_key(name))
                    r.generate(plan=self.plan, seed=self.seed, stream=stream,
                               owner_times=times[pop.table])

    def _build_tables(self) -> None:
        """Rows of every read-only table: from its source, or from the recipe that builds it."""
        plan = self.plan
        self.tables: dict[str, dict[str, np.ndarray]] = {}
        self.weights: dict[str, np.ndarray] = {}
        self.cumw: dict[str, np.ndarray] = {}
        for t in plan.tables:
            rows = None
            if t.source is not None:
                stream = rng.name_key(t.name)
                rows = t.source.generate(t.source.n, t, self.seed, stream)
                if getattr(t.source, "weight", None) is not None:
                    w = np.asarray(t.source.row_weights(self.seed, stream), np.float64)
                    self.weights[t.name] = w
                    self.cumw[t.name] = self._cumw(w)
            else:
                for r in self._recipes():
                    built = r.table_rows(t.name)
                    if built is not None:
                        rows = built
                        break
            if rows is not None:
                self.tables[t.name] = {c.name: np.asarray(rows[c.name], slab_dtype(c))
                                       for c in t.cols}

    @staticmethod
    def _cumw(w: np.ndarray) -> np.ndarray:
        """Normalised cumulative weight ending at exactly 1.0 (for `sample_by_weight`)."""
        cum = np.cumsum(w)
        if len(w) == 0 or not cum[-1] > 0:
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
            stream = rng.mix(rng.name_key(part.name), rng.name_key("init"))
            recipe_vals = init.init(n_items=len(order), n_shards=part.n, seed=self.seed,
                                    stream=stream, item_weights=self.weights.get(part.items))
        arrays = []
        for field, decl in part.state.items():
            m = _STATE_RE.match(decl)
            dt = np.dtype(_NP[m.group(1)])
            per_item = m.group(2) is not None
            size = len(order) if per_item else part.n
            v = recipe_vals.get(field) if recipe_vals is not None else (
                init.get(field) if isinstance(init, dict) else None)
            if v is None:                            # a `ref` field starts at std.NULL (D38)
                arrays.append(np.full(size, _NULL, dt) if m.group(1) == "ref"
                              else np.zeros(size, dt))
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
            "kc": self.kc, "nopay": np.zeros((1, PAYLOAD_W), np.int64),
            "node_cap": int(self._node_cap()),
            "bnd_delta": self._bnd_array(lambda b: b.min_latency_us)}
        self._W = tuple(parts[f] for f in WORLD_FIELDS)

    def _bnd_array(self, value) -> np.ndarray:
        """int64 per boundary code (at least one entry, so Numba sees a typed array)."""
        out = np.zeros(max(1, len(self.plan.boundaries)), np.int64)
        for b in self.plan.boundaries:
            out[b.code] = value(b)
        return out

    def _build_route(self) -> None:
        """The route tuple `R` (see `engine.route`) and the buffers of the round loop."""
        plan, hid, G = self.plan, self.hidden, self.G
        shard_bases = [self.slot_base[p.name] for p in plan.partitions if p.kind == "shard"]
        self.shard_lo = min(shard_bases, default=G)       # shards occupy [shard_lo, G)

        def base(b):
            to = plan.partition(b.to)
            return self.slot_base[to.name] if to.kind == "shard" else 0

        self.msg = np.array([0, self.run.engine.max_messages_per_step], np.int64)
        self.next_t = np.full(G, _I64_MAX, np.int64)      # calendar key per owner slot
        self._tmask = np.zeros(G, np.uint8)
        self._tlist = np.zeros(G, np.int64)
        self._tn = np.zeros(1, np.int64)
        pay = self.payload
        self.R = (hid.qhead, hid.cseq, hid.gen, hid.alive, hid.pending, hid.susp_t,
                  hid.susp_delta, self._reserve_pool(),
                  pay.as_tuple()[:2] + (pay.reserve_head, pay.reserve_n),
                  self._bnd_array(base), self.counters, self.msg,
                  np.zeros(G, np.int64), np.zeros(1, np.int64),
                  self._tmask, self._tlist, self._tn,
                  np.zeros(G, np.int64), np.zeros(1, np.int64), np.zeros(G, np.uint8),
                  self._bnd_array(lambda b: 0), np.zeros(G, np.int64))
        self.pending_creates: list[_Creation] = []
        self.admissions = 0                               # created owners admitted this step
        self.run_buf = np.zeros(G, np.int64)              # runnable slots (compiled rounds)
        self.shard_buf = np.zeros(max(1, G - self.shard_lo), np.int64)
        self.round_log = np.zeros((256, 2), np.int64)
        self.round_state = np.zeros(8, np.int64)

    # ------------------------------------------------------------------ admission
    def _reserve_pool(self) -> tuple:
        """The node pool tuple with the reserve list in place of the worker free lists."""
        return self.pool.as_tuple()[:8] + (self.pool.reserve_head, self.pool.reserve_n)

    def _take_reserve_nodes(self, need: int) -> None:
        """Ensure the reserve holds `need` nodes (called between phases, never concurrently)."""
        with self._reserve_lock:
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
            self._reset_slots(part, g, (part.ptype_code << 56) | ords, ords,
                              instance_keys(pop.table, ords))
            cols = self.plan.table(pop.table).cols
            for c, arr, v in zip(cols, self.state[part.name], self.state_init[part.name],
                                 strict=True):
                arr[lslots] = pop.attrs[c.name][ords] if c.name in pop.attrs else v
            self._take_reserve_nodes(k * len(pop.procs))
            ok = _queue_starts(self._reserve_pool(), hid.qhead, hid.cseq, g, pop.times[lo:hi],
                               pop.procs, PRIO_MESSAGE)
            assert ok, "reserve nodes were checked above"
            pop.next = hi
            rt.mark_all(self.R, g, len(g))
            admitted.append(g)
        return np.concatenate(admitted) if admitted else np.zeros(0, np.int64)

    def _reset_slots(self, part: Any, g: np.ndarray, pid: Any, self_id: Any, inst: Any) -> None:
        """Fresh hidden fields and local rows for newly admitted owner slots `g`."""
        hid = self.hidden
        hid.pid[g] = pid
        hid.alive[g] = 1
        for name in ("clock", "rseq", "cseq", "pending", "susp_delta"):
            getattr(hid, name)[g] = 0
        hid.occ[g] = 0
        hid.ordn[g] = 0
        hid.retire_at[g] = _I64_MAX
        hid.susp_t[g] = _I64_MAX
        hid.last_t[g] = _FILL["last_t"]
        hid.inst[g] = inst
        hid.self_id[g] = self_id
        lslots = hid.lslot[g]
        for p in self.plan.processes:
            if p.partition == part.name and p.kernel.local is not None:
                for (kind, _), arr in zip(p.kernel.local.fields.values(), self.locals[p.name],
                                          strict=True):
                    arr[lslots] = _fill_value(arr.dtype) if kind == "ref" else 0

    def admit_created(self, limit_t: int) -> np.ndarray:
        """Admit every pending creation with time < `limit_t`; returns their global slots.

        In routing-key order, each created owner gets a free slot, the created row's columns as
        state, `self_id = pid = handle` (provisional; D12), `inst = mix(creator inst, lamport,
        ns, k)` and a `START` at the creation time per process started by `on_created`.

        `k` is the row's ordinal among the rows of its namespace created by the same commit: the
        handle's per-step ordinal minus the commit's first one. A commit's creations share its
        time, so they are routed and admitted together, and `(creator, lamport)` names the
        commit. The per-step ordinal itself would make `inst` (every draw of the created owner)
        depend on whether an earlier commit of the creator fell in the same step (spec §12).
        """
        due = sorted((c for c in self.pending_creates if c.time < limit_t),
                     key=lambda c: (c.time, c.prio, c.cause, c.src_pid, c.src_seq))
        if not due:
            return np.zeros(0, np.int64)
        self.pending_creates = [c for c in self.pending_creates if c.time >= limit_t]
        plan, hid = self.plan, self.hidden
        first: dict[tuple[int, int, int], int] = {}          # (creator, lamport, ns) -> ordinal
        for c in due:
            key, o = (c.src_g, c.cause, c.ns), handle_ordinal(c.handle)
            first[key] = min(first.get(key, o), o)
        rows = self._created_rows({plan.namespaces[c.ns] for c in due})
        owner_of = {p.table: p for p in plan.partitions if p.kind == "owner"}
        limit = int(self.run.budget.max_admissions_per_step)
        admitted = []
        for c in due:
            ns = plan.namespaces[c.ns]
            part, proc = owner_of[ns], plan.processes[c.action].name
            self.admissions += 1
            if self.admissions > limit:
                raise CapExceeded("max_admissions_per_step", limit, self.admissions, process=proc)
            free = self.free_lslots[part.name]
            if not len(free):
                raise CapExceeded("live_partition_state", part.max_live, part.max_live + 1,
                                  process=proc)
            ls, self.free_lslots[part.name] = int(free[0]), free[1:]
            g = self.slot_base[part.name] + ls
            k = handle_ordinal(c.handle) - first[(c.src_g, c.cause, c.ns)]
            inst = _as_i64(rng.mix(int(hid.inst[c.src_g]), c.cause, c.ns, k))
            self._reset_slots(part, np.array([g]), c.handle, c.handle, inst)
            row = rows[ns](c.handle)
            for col, arr in zip(plan.table(ns).cols, self.state[part.name], strict=True):
                arr[ls] = row[col.name]
            procs = [p.action_id for p in plan.processes if p.partition == part.name
                     and p.start is not None and p.start.table == ns]
            self._take_reserve_nodes(len(procs))
            P = self._reserve_pool()
            for a in procs:
                sq = int(hid.cseq[g])
                hid.cseq[g] = sq + 1
                q_push(P, 0, hid.qhead, g, c.time, PRIO_MESSAGE, c.cause, sq, START, a, 0, -1)
            rt.mark_touched(self.R, g)
            admitted.append(g)
        return np.array(admitted, np.int64)

    def _created_rows(self, namespaces: set[str]) -> dict[str, _CreatedIndex]:
        """Per namespace, this step's lookup `handle -> create-slab row`, brought up to date.

        Indexing is incremental, so a step's admission calls index each created row once
        (`created_rows_indexed`): per worker, the chunks flushed since the last call (the first
        of them starts with the live rows indexed last time, which are skipped), then the live
        slab rows added since. Live rows are copied, as the slab is reused after a flush; chunk
        rows are final. `take_chunks` drops the index with the step's chunks."""
        out = {}
        for ns in namespaces:
            idx = self._created_index.get(ns)
            if idx is None:
                idx = self._created_index[ns] = _CreatedIndex(ns)
            res = f"creates:{ns}"
            for w, slab in enumerate(self.slabs):
                n_chunks, n_live = idx.seen.get(w, (0, 0))
                chunks = self.chunks[w]
                if len(chunks) > n_chunks:
                    skip = n_live
                    for ch in chunks[n_chunks:]:
                        cols = ch.creates.get(ns)
                        if cols is not None:
                            self.created_rows_indexed += idx.add(cols, skip,
                                                                 len(cols["handle"]))
                        skip = 0
                    n_live = 0
                n = int(slab.cnt[slab.resources.index(res)])
                if n > n_live:
                    live = {k: v[n_live:n].copy() for k, v in slab.buffers[res].items()}
                    self.created_rows_indexed += idx.add(live, 0, n - n_live)
                idx.seen[w] = (len(chunks), n)
            out[ns] = idx
        return out

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
        out = self._outs[worker]
        i = 0
        while True:
            status, i = self.eng.run_partitions(self._W, out, worker, slots, i, int(limit_t),
                                                bool(owners))
            if status == DONE:
                self._trim_nodes(worker)             # nodes freed by the last commands
                return
            self.handle_status(worker, status)

    def handle_status(self, worker: int, status: int) -> None:
        """Make room after a runner status: flush or move aside a full buffer, refill nodes."""
        slab = self.slabs[worker]
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

    def _trim_nodes(self, worker: int) -> None:
        """Give nodes above a forced free-list size back to the reserve; never refill or fail
        (a run that ends cleanly must not trip over an empty reserve)."""
        cap = self._node_cap()
        if cap < 0:
            return
        with self._reserve_lock:
            have = int(self.pool.free_n[worker])
            if have > cap:
                self.pool.release(worker, have - cap)

    def _node_cap(self) -> int:
        force = self.run.engine.force_capacity.get("timers")
        return -1 if force is None else int(force)

    def _refill_nodes(self, worker: int) -> None:
        """Bring `worker`'s node free list to its forced size (trimming or refilling), or refill
        it by `NODE_CHUNK`. Threads share the reserve list, so this holds the reserve lock."""
        pool, cap = self.pool, self._node_cap()
        with self._reserve_lock:
            have = int(pool.free_n[worker])
            if cap >= 0 and have >= cap:
                pool.release(worker, have - cap)   # == cap: a kernel needs more than forced;
                return                             # the retry cap ends the run
            if pool.reserve_n[0] == 0:
                raise CapExceeded("timer_heaps", pool.capacity, pool.in_use() + 1)
            chunk = NODE_CHUNK if cap < 0 else cap - have
            pool.refill(worker, min(chunk, int(pool.reserve_n[0])))

    def _take_reserve_payload(self, need: int) -> None:
        """Ensure the payload reserve holds `need` rows (between phases; under the node lock)."""
        pay = self.payload
        with self._reserve_lock:
            if pay.reserve_n[0] < need:
                pay.splice_all()
            if pay.reserve_n[0] < need:
                raise CapExceeded("requests_and_inboxes", pay.capacity, pay.in_use() + need)

    # ------------------------------------------------------------------ rounds support
    def begin_step(self, t0: int, t1: int) -> None:
        """Reset the per-step bookkeeping (touched slots, message and admission counts)."""
        n = int(self._tn[0])
        self._tmask[self._tlist[:n]] = 0
        self._tn[0] = 0
        self.msg[0] = 0
        self.admissions = 0

    @property
    def touched(self) -> np.ndarray:
        """Global slots touched this step (ran, received a command or were created), sorted."""
        return np.sort(self._tlist[:int(self._tn[0])])

    def collect(self, t0: int, t1: int) -> np.ndarray:
        """Owners whose next command (as of their last step) falls in [t0, t1)."""
        buf = np.zeros(self.G, np.int32)
        n = cal_collect(self.calendar.as_tuple(), self.next_t, t0, t1, buf)
        return buf[:n].astype(np.int64)

    def end_step(self, t1: int) -> None:
        """Calendar entries for every touched owner that waits on nothing (next command >= t1)."""
        hid = self.hidden
        gs = self.touched
        gs = gs[gs < self.shard_lo]
        heads = hid.qhead[gs]
        ok = (heads >= 0) & (hid.pending[gs] == 0) & (hid.alive[gs] == 1)
        ts = np.where(ok, self.pool.time[np.maximum(heads, 0)], _I64_MAX)
        self.next_t[gs] = ts
        gs, ts = gs[ok], ts[ok]
        if len(ts) and ts.min() < t1:
            raise EngineError("step closed with an owner runnable before its end")
        C, i = self.calendar.as_tuple(), 0
        while i < len(gs):
            j = _cal_push_all(C, gs, ts, i)
            if j < len(gs) and j == i:
                self.calendar.compact(self.next_t)         # drops stale entries
                j = _cal_push_all(C, gs, ts, i)
                if j == i:
                    raise EngineError("calendar has no free entry after compaction")
            i = j

    def note_suspended(self, slots: np.ndarray) -> None:
        slots = np.ascontiguousarray(slots, np.int64)
        rt.note_suspended(self.R, slots, len(slots))

    def mark_touched(self, slots: np.ndarray) -> None:
        slots = np.ascontiguousarray(slots, np.int64)
        rt.mark_all(self.R, slots, len(slots))

    def horizon(self, t1: int) -> int:
        """The safe horizon of this round (D5): suspended owners and pending creations."""
        create_min = min((c.time for c in self.pending_creates), default=_I64_MAX)
        return int(rt.horizon(self.R, int(t1), int(create_min)))

    def shards_below(self, limit: int) -> np.ndarray:
        n = rt.shards_below(self.R, self.shard_lo, self.G, int(limit), self.shard_buf)
        return self.shard_buf[:n].copy()

    def take_runnable(self, t1: int) -> np.ndarray:
        """Owners woken by routing that have nothing pending and a command before t1."""
        n = rt.take_runnable(self.R, int(t1), self.run_buf)
        return self.run_buf[:n].copy()

    def command_count(self) -> int:
        return int(rt.command_count(self.counters))

    def next_command_time(self, owners: bool) -> int:
        """Earliest queued command time over live owners (or over shards); I64_MAX if none."""
        lo, hi = (0, self.shard_lo) if owners else (self.shard_lo, self.G)
        heads = self.hidden.qhead[lo:hi]
        live = (heads >= 0) & (self.hidden.alive[lo:hi] == 1)
        return int(self.pool.time[heads[live]].min()) if live.any() else _I64_MAX

    def route(self) -> None:
        """Route every worker's outbox rows (live and moved aside) and empty those outboxes.

        Creation rows join `pending_creates`; the rest go through `engine.route.route_outbox`,
        which delivers them in (time, prio, cause, src_pid, src_seq) order.
        """
        parts: list[dict[str, np.ndarray]] = []
        for w, slab in enumerate(self.slabs):
            parts += self.pending_outbox[w]
            n = int(slab.cnt[slab.resources.index("requests")])
            if n:
                parts.append({**{c: a[:n] for c, a in slab.outbox.items()},
                              "pay": slab.outbox_pay[:n]})
        if not parts:
            return
        cols = (*OUTBOX_COLS, "pay")
        ob = parts[0] if len(parts) == 1 else {c: np.concatenate([p[c] for p in parts])
                                                for c in cols}
        n = len(ob["kind"])
        creates = np.flatnonzero(ob["kind"] == OB_CREATE)
        for i in creates:
            self.pending_creates.append(_Creation(
                int(ob["time"][i]), int(ob["prio"][i]), int(ob["cause"][i]),
                int(ob["src_pid"][i]), int(ob["src_seq"][i]), int(ob["bnd"][i]),
                int(ob["dst"][i]), int(ob["pay"][i, 7]), int(ob["pay"][i, 10])))
        tup = tuple(np.ascontiguousarray(ob[c]) for c in cols)
        while True:
            status, k = rt.route_outbox(self.R, tup, n, True)
            if status == rt.ROUTED:
                break
            if status == rt.NEED_MESSAGES:
                raise CapExceeded("requests_and_inboxes", int(self.msg[1]), int(k))
            if status == rt.NEED_NODES:
                self._take_reserve_nodes(int(k))
            elif status == rt.NEED_PAYLOAD:
                self._take_reserve_payload(int(k))
            else:
                raise EngineError(f"route_outbox returned unknown status {status}")
        for w, slab in enumerate(self.slabs):
            self.pending_outbox[w].clear()
            slab.reset_outbox()

    def route_stale_response_for_test(self) -> int:
        """TEST HOOK ONLY (`_for_test`): route one response to a slot whose generation changed.

        Picks an owner waiting for a response (running owners until one requests, if none is
        waiting), runs the shards so its request is answered in a fresh outbox, bumps the
        owner's slot generation as a retirement and reuse would, routes, and returns how many
        responses routing dropped as late.
        """
        hid = self.hidden
        owners = np.arange(self.shard_lo)
        for g in owners[(hid.alive[owners] == 1) & (hid.qhead[owners] >= 0)]:
            if (hid.pending[owners] > 0).any():
                break
            self.run_slots(0, np.array([g]), _I64_MAX, owners=True)
            self.route()
        waiting = owners[hid.pending[owners] > 0]
        if not len(waiting):
            raise EngineError("no owner made a request")
        g = int(waiting[0])
        self.run_slots(0, np.arange(self.shard_lo, self.G), int(hid.susp_t[g]) + 1,
                       owners=False)
        before = self.stats["late_messages"]
        hid.gen[g] += 1
        self.route()
        return self.stats["late_messages"] - before

    def _flush(self, worker: int) -> None:
        """Move `worker`'s filled slab rows into its chunks and enforce the step output cap
        (spec section 10) on everything flushed this step, before the step accumulates more."""
        chunk = self.slabs[worker].flush()
        parts = [*chunk.records.values(), *chunk.creates.values()]
        rows = sum(len(next(iter(p.values()))) for p in parts)
        if not rows:
            return
        n_bytes = sum(a.nbytes for p in parts for a in p.values())
        self.chunks[worker].append(chunk)
        budget = self.run.budget
        with self._step_lock:
            self.step_rows += rows
            self.step_bytes += n_bytes
            total_rows, total_bytes = self.step_rows, self.step_bytes
        if total_rows > budget.max_step_rows:
            raise CapExceeded("step_output", int(budget.max_step_rows), int(total_rows))
        if budget.max_step_bytes is not None and total_bytes > budget.max_step_bytes:
            raise CapExceeded("step_output", int(budget.max_step_bytes), int(total_bytes))

    def flush_all(self) -> None:
        """Flush every worker slab into its `chunks` list."""
        for w in range(self.threads):
            self._flush(w)

    def take_chunks(self) -> list[StepChunk]:
        """Return and clear every flushed chunk (all workers)."""
        out = [c for chunks in self.chunks for c in chunks]
        for chunks in self.chunks:
            chunks.clear()
        self._created_index = {}
        self.step_rows = self.step_bytes = 0
        return out

    @property
    def stats(self) -> dict[str, Any]:
        c = self.counters.sum(axis=0)
        rej = self.rejects.sum(axis=0)
        return {"rejects": {p.name: int(rej[p.action_id]) for p in self.plan.processes},
                "retries": int(c[COUNTERS.index("retries")]),
                "late_messages": int(c[COUNTERS.index("late_messages")]),
                "continuations": int(c[COUNTERS.index("continuations")]),
                "commands": int(c[COUNTERS.index("commands")]),
                "requests_by_boundary": {b.name: int(self.R[rt.RT_BND_REQ][b.code])
                                         for b in self.plan.boundaries
                                         if b.kind == "request"}}
