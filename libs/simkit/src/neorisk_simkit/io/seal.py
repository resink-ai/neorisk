"""Sealing a frontier step (spec sections 12 and 13; decisions D11, D14, D19, D20).

`seal_step` turns everything the workers flushed during one step into typed Arrow tables:

1. collect every worker's `StepChunk`s;
2. give the rows created this step dense indices per namespace (`id_bases[<ns>]` + rank by
   `(pid, ordinal)`, spec §12: creator `partition_id` order, then local ordinal); created
   owners get `pid = ptype_code << 56 | dense`;
3. remap provisional handles (D11, D38) in records, created rows, the state, local `ref` fields
   and `self_id`/`pid` of touched owners, the `ref` state and local `ref` fields of touched
   shards, and the tag, user payload and sender (column 9) of every command queued at a touched
   slot and of every owner-to-owner message sent this step (D73); a provisional value that
   matches no row of this step fails the run;
4. free the slots of owners that retired idle this step (`alive = 0`, `gen += 1`, slot reusable;
   a population owner leaves `World.pop_slot`);
5. number events and postings per table (`id_bases["event:<name>"]` + rank by `(pid, seq)`)
   and map every ID to its public value (`feistel63` keyed by the table name);
6. sort each table by the canonical key `(time, lamport, partition_id, seq)`;
7. count the step's output rows and bytes (the cap, `CapExceeded("step_output", ...)`, is
   enforced earlier, on every slab flush, over all buffers including `p.ids` allocations);
8. warm-up steps keep their created entities but drop event, posting and history rows (D20);
   the event and posting tables named in `law_tables` are kept apart in `warmup_rows` first
   (F-01: law reducers start from the opening snapshot), numbered from a throwaway copy of
   `id_bases`, so exported IDs do not change;
9. run the structural checks on exported steps.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

import numpy as np
import pyarrow as pa
from numba import njit

from neorisk_simkit.engine.abi import START
from neorisk_simkit.engine.cmdq import PAY_CONTINUE
from neorisk_simkit.engine.errors import EngineError
from neorisk_simkit.engine.identity import (
    FLAG,
    assign_dense,
    feistel63_array,
    feistel_key,
    remap_inplace,
)
from neorisk_simkit.engine.slabs import BufferSpec, buffer_specs
from neorisk_simkit.io.consts import I64_MAX, NULL, TS
from neorisk_simkit.spec.types import COMMON_COLUMNS, LType, arrow_type

_USER_PAYLOAD = 7                                # payload columns 0..6 carry user values (D17)
_PAY_SENDER = 9                                  # payload column 9: src_self_id (`cmd.sender`, D38)

HISTORY_HEAD = ("entity_id", "valid_from", "lamport", "partition_id", "seq")
ENTITY_HEAD = ("id", "created_at", "origin")
ORIGIN_CREATED = "created"


@dataclass(frozen=True)
class SealedStep:
    step: int
    t_start: int
    t_end: int
    exported: bool
    events: dict[str, pa.Table]                  # event type -> rows (canonical order)
    history: dict[str, pa.Table]                 # change group -> rows (canonical order)
    entities: dict[str, pa.Table]                # created table -> rows created this step
    stats: dict[str, Any]
    postings: dict[str, pa.Table] = dataclasses.field(default_factory=dict)  # D45
    # this step's delta per accumulator (D46), warm-up steps included
    accumulators: dict[str, int] = dataclasses.field(default_factory=dict)
    # warm-up steps only: the rows of the tables the laws read, before D20 drops them (F-01);
    # fed to `LawBook.step(..., exported=False)` and cleared, never written
    warmup_rows: dict[str, pa.Table] = dataclasses.field(default_factory=dict)
    # owner slots freed at this seal; their state stays intact until a later admission, so
    # state laws still see each retired owner's final values (D47)
    retired: np.ndarray = dataclasses.field(default_factory=lambda: np.zeros(0, np.int64))


# ---------------------------------------------------------------------------- Arrow columns
def public_ids(seed: int, name: str, dense: np.ndarray) -> np.ndarray:
    """Exported IDs of the dense indices `dense` of the table / namespace `name`."""
    return feistel63_array(np.ascontiguousarray(dense, np.int64), feistel_key(seed, name))


def column_array(values: np.ndarray, lt: LType, valid: np.ndarray | None, seed: int) -> pa.Array:
    """One column as Arrow (types from `arrow_type`): refs become public IDs, `NULL` refs and
    rows with `valid == 0` become null, cats become `dictionary<int16, string>`, text is null."""
    n = len(values)
    ok = None if valid is None else np.asarray(valid, bool)
    if lt.kind == "text":
        return pa.nulls(n, pa.string())
    if lt.kind == "ref":
        v = np.asarray(values, np.int64)
        ok = (v != NULL) if ok is None else (ok & (v != NULL))
        out = np.zeros(n, np.int64)
        if ok.any():
            out[ok] = public_ids(seed, lt.target, v[ok])
        return pa.array(out, pa.int64(), mask=~ok)
    mask = None if ok is None else ~ok
    if lt.kind == "cat":
        idx = pa.array(np.asarray(values, np.int16), pa.int16(), mask=mask)
        return pa.DictionaryArray.from_arrays(idx, pa.array(list(lt.values), pa.string()),
                                              safe=False)   # range is a structural check
    if lt.kind == "ts":
        return pa.array(np.asarray(values, np.int64), pa.int64(), mask=mask).cast(TS)
    if lt.kind == "bool":
        return pa.array(np.asarray(values) != 0, pa.bool_(), mask=mask)
    return pa.array(values, arrow_type(lt), mask=mask)


def _ts(values: np.ndarray) -> pa.Array:
    return pa.array(np.asarray(values, np.int64), pa.int64()).cast(TS)


def _table(names: list[str], arrays: list[pa.Array], nullable: list[bool]) -> pa.Table:
    schema = pa.schema([pa.field(n, a.type, nullable=nb)
                        for n, a, nb in zip(names, arrays, nullable, strict=True)])
    return pa.Table.from_arrays(arrays, schema=schema)


def _user_cols(rows: dict[str, np.ndarray], cols, order: np.ndarray, seed: int):
    names, arrays, nullable = [], [], []
    for c in cols:
        valid = rows[f"valid_{c.name}"][order] if c.ltype.nullable else None
        names.append(c.name)
        arrays.append(column_array(rows[c.name][order], c.ltype, valid, seed))
        nullable.append(c.ltype.nullable)
    return names, arrays, nullable


def _canonical(rows: dict[str, np.ndarray]) -> np.ndarray:
    return np.lexsort((rows["seq"], rows["pid"], rows["lamport"], rows["time"]))


def event_table(e: Any, rows: dict[str, np.ndarray], id_bases: dict[str, int],
                seed: int) -> pa.Table:
    """The rows of event type `e` with public IDs, in canonical order; advances its id base."""
    n = len(rows["time"])
    key = f"event:{e.name}"
    base = id_bases.get(key, 0)
    dense = assign_dense(rows["pid"], rows["seq"], base)
    id_bases[key] = base + n
    order = _canonical(rows)
    common = {
        "event_id": pa.array(public_ids(seed, e.name, dense[order]), pa.int64()),
        "event_type": pa.array(np.full(n, e.name, object), pa.string()),
        "event_time": _ts(rows["time"][order]),
        "lamport": pa.array(rows["lamport"][order], pa.int64()),
        "partition_id": pa.array(rows["pid"][order], pa.int64()),
        "seq": pa.array(rows["seq"][order], pa.int32()),
        "cause_id": pa.nulls(n, pa.int64()),                     # D14
        "action_id": pa.array(rows["action"][order], pa.int16()),
    }
    names = [c for c, _ in COMMON_COLUMNS]
    arrays = [common[c] for c in names]
    nullable = [lt.nullable for _, lt in COMMON_COLUMNS]
    un, ua, unb = _user_cols(rows, e.cols[len(COMMON_COLUMNS):], order, seed)
    return _table(names + un, arrays + ua, nullable + unb)


def history_table(g: Any, rows: dict[str, np.ndarray], seed: int) -> pa.Table:
    """The change rows of group `g` (D19), in canonical order."""
    order = _canonical(rows)
    arrays = [pa.array(public_ids(seed, g.table, rows["entity_id"][order]), pa.int64()),
              _ts(rows["time"][order]),
              pa.array(rows["lamport"][order], pa.int64()),
              pa.array(rows["pid"][order], pa.int64()),
              pa.array(rows["seq"][order], pa.int32())]
    un, ua, unb = _user_cols(rows, g.cols, order, seed)
    return _table([*HISTORY_HEAD, *un], arrays + ua, [False] * len(HISTORY_HEAD) + unb)


def entity_table(name: str, cols, dense: np.ndarray, created_at: np.ndarray,
                 origin: np.ndarray | str, rows: dict[str, np.ndarray], seed: int,
                 valid: dict[str, np.ndarray] | None = None) -> pa.Table:
    """Entity rows in dense order: public `id`, `created_at`, `origin`, then the table columns
    (`valid[col]` masks nullable columns; otherwise `rows["valid_<col>"]` when present)."""
    order = np.argsort(dense, kind="stable")
    n = len(dense)
    org = np.full(n, origin, object) if isinstance(origin, str) else np.asarray(origin)[order]
    arrays = [pa.array(public_ids(seed, name, dense[order]), pa.int64()),
              _ts(created_at[order]), pa.array(org, pa.string())]
    names, nullable = list(ENTITY_HEAD), [False, False, False]
    for c in cols:
        v = (valid or {}).get(c.name)
        if v is None and c.ltype.nullable and f"valid_{c.name}" in rows:
            v = rows[f"valid_{c.name}"]
        names.append(c.name)
        arrays.append(column_array(rows[c.name][order], c.ltype,
                                   None if v is None else v[order], seed))
        nullable.append(c.ltype.nullable)
    return _table(names, arrays, nullable)


# ---------------------------------------------------------------------------- remapping
@njit(cache=True, nogil=True)
def _queued_nodes(qhead, nxt, slots):
    """Every command node queued at `slots`, in queue order per slot."""
    n = 0
    for i in range(slots.shape[0]):
        node = qhead[slots[i]]
        while node >= 0:
            n += 1
            node = nxt[node]
    out = np.empty(n, np.int64)
    k = 0
    for i in range(slots.shape[0]):
        node = qhead[slots[i]]
        while node >= 0:
            out[k] = node
            k += 1
            node = nxt[node]
    return out


class _Remap:
    """Provisional handle -> dense index (refs) or final partition id (pid columns)."""

    def __init__(self, handles: np.ndarray, dense: np.ndarray, pids: np.ndarray):
        order = np.argsort(handles, kind="stable")
        self.src = np.ascontiguousarray(handles[order])
        self.dense = dense[order]
        self.pid = pids[order]

    def apply(self, values: np.ndarray, where: str, *, pid: bool = False) -> None:
        if not len(values):
            return
        misses = remap_inplace(values, self.src, self.pid if pid else self.dense)
        if misses:
            left = values[(values >= 0) & ((values & FLAG) != 0)]
            raise EngineError(f"unresolved handle {int(left[0]):#x} in {where} "
                              f"({misses} value(s) match no row created this step)")

    def apply_copy(self, arr: np.ndarray, idx: np.ndarray, where: str, *,
                   pid: bool = False) -> None:
        """Remap `arr[idx]` (rows of a 1-D or 2-D array) and write it back."""
        if not len(idx):
            return
        v = np.ascontiguousarray(arr[idx])
        flat = v.reshape(-1)
        self.apply(flat, where, pid=pid)
        arr[idx] = v


def _merge(chunks: list[Any], spec: BufferSpec) -> dict[str, np.ndarray]:
    source = "creates" if spec.kind == "create" else "records"
    parts = [getattr(c, source)[spec.name] for c in chunks if spec.name in getattr(c, source)]
    parts = [p for p in parts if len(p[spec.head[0][0]])]
    if not parts:
        return {name: np.zeros(0, dt) for name, dt in spec.fields}
    if len(parts) == 1:
        return dict(parts[0])
    return {name: np.concatenate([p[name] for p in parts]) for name, _ in spec.fields}


def _remap_world(world: Any, remap: _Remap) -> np.ndarray:
    """Remap handles held by touched slots (owners and shards); returns the touched owner
    slots."""
    plan, hid = world.plan, world.hidden
    touched = np.asarray(world.touched, np.int64)
    owners = touched[touched < world.shard_lo]
    for part in plan.partitions:
        if part.kind != "owner":
            continue
        base = world.slot_base[part.name]
        gs = owners[(owners >= base) & (owners < base + part.max_live)]
        if not len(gs):
            continue
        ls = hid.lslot[gs]
        for c, arr in zip(plan.table(part.table).cols, world.state[part.name], strict=True):
            if c.ltype.kind == "ref":
                remap.apply_copy(arr, ls, f"state {part.table}.{c.name}")
        for p in plan.processes:
            if p.partition != part.name or p.kernel.local is None:
                continue
            for (fname, (kind, _)), arr in zip(p.kernel.local.fields.items(),
                                               world.locals[p.name], strict=True):
                if kind == "ref":
                    remap.apply_copy(arr, ls, f"local {p.name}.{fname}")
        remap.apply_copy(hid.self_id, gs, f"self_id of {part.name}")
        remap.apply_copy(hid.pid, gs, f"pid of {part.name}", pid=True)
    _remap_shards(world, remap, touched[touched >= world.shard_lo])
    pool = world.pool
    nodes = _queued_nodes(hid.qhead, pool.next, touched)
    if len(nodes):
        tagged = nodes[(pool.pay[nodes] != PAY_CONTINUE) & (pool.kind[nodes] != START)]
        remap.apply_copy(pool.tag, tagged, "a queued command tag")
        rows = pool.pay[nodes]
        rows = rows[rows >= 0].astype(np.int64)
        if len(rows):
            block = np.ascontiguousarray(world.payload.rows[rows, :_USER_PAYLOAD])
            remap.apply(block.reshape(-1), "a queued command payload")
            world.payload.rows[rows, :_USER_PAYLOAD] = block
            sender = np.ascontiguousarray(world.payload.rows[rows, _PAY_SENDER])
            remap.apply(sender, "a queued command sender")
            world.payload.rows[rows, _PAY_SENDER] = sender
    hid.ordn[touched] = 0                     # create ordinals are per step (D11)
    _remap_owner_messages(world, remap)
    return owners


def _remap_owner_messages(world: Any, remap: _Remap) -> None:
    """Remap the carried owner-to-owner messages sent this step (D73) like queued commands:
    their tag, user payload and sender, so a handle created this step reaches its target as
    its final value."""
    from neorisk_simkit.engine.slabs import OUTBOX_COLS

    cols, pay, n = world.o2o
    lo, hi = int(world.o2o_step_lo), int(n[0])
    if hi <= lo:
        return
    tag = np.ascontiguousarray(cols[lo:hi, OUTBOX_COLS.index("tag")])
    remap.apply(tag, "an owner message tag")
    cols[lo:hi, OUTBOX_COLS.index("tag")] = tag
    block = np.ascontiguousarray(pay[lo:hi, :_USER_PAYLOAD])
    remap.apply(block.reshape(-1), "an owner message payload")
    pay[lo:hi, :_USER_PAYLOAD] = block
    sender = np.ascontiguousarray(pay[lo:hi, _PAY_SENDER])
    remap.apply(sender, "an owner message sender")
    pay[lo:hi, _PAY_SENDER] = sender
    world.o2o_step_lo = hi


def _remap_shards(world: Any, remap: _Remap, shards: np.ndarray) -> None:
    """Remap the `ref` state fields (scalar: at the shard index; per item: over the shard's item
    range) and the `ref` local fields of every touched shard slot in `shards` (D38)."""
    from neorisk_simkit.engine.layout import _STATE_RE

    plan, hid = world.plan, world.hidden
    for part in plan.partitions:
        if part.kind == "owner":
            continue
        base = world.slot_base[part.name]
        gs = shards[(shards >= base) & (shards < base + part.n)]
        if not len(gs):
            continue
        idx = hid.lslot[gs].astype(np.int64)
        items = None
        for (field, decl), arr in zip(part.state.items(), world.state[part.name], strict=True):
            m = _STATE_RE.match(decl)
            if m.group(1) != "ref":
                continue
            where = f"state {part.name}.{field}"
            if m.group(2) is None:
                remap.apply_copy(arr, idx, where)
                continue
            if items is None:
                offs = world.offs[part.name]
                items = np.concatenate([np.arange(offs[i], offs[i + 1], dtype=np.int64)
                                        for i in idx])
            remap.apply_copy(arr, items, where)
        for p in plan.processes:
            if p.partition != part.name or p.kernel.local is None:
                continue
            for (fname, (kind, _)), arr in zip(p.kernel.local.fields.items(),
                                               world.locals[p.name], strict=True):
                if kind == "ref":
                    remap.apply_copy(arr, idx, f"local {p.name}.{fname}")


def _free_retired(world: Any, owners: np.ndarray) -> np.ndarray:
    """Free owners that retired idle this step; an owner that got new commands after retiring
    (or waits on a response) stays live. Returns the freed global slots."""
    hid = world.hidden
    r = owners[hid.retire_at[owners] != I64_MAX]
    if not len(r):
        return np.zeros(0, np.int64)
    idle = (hid.qhead[r] < 0) & (hid.pending[r] == 0)
    hid.retire_at[r] = I64_MAX
    gone = r[idle]
    hid.alive[gone] = 0
    hid.gen[gone] += 1
    world.next_t[gone] = I64_MAX
    for part in world.plan.partitions:
        if part.kind != "owner":
            continue
        base = world.slot_base[part.name]
        mine = gone[(gone >= base) & (gone < base + part.max_live)]
        if len(mine):                       # to the back of the type's ring, sorted (D44)
            world.FS.give(world.owner_type[part.name], hid.lslot[mine])
            slot_of = world.pop_slot.get(part.table)
            pop = mine[hid.created[mine] == 0]
            if slot_of is not None and len(pop):   # population owners leave pop_slot (D73)
                slot_of[hid.pid[pop] & ((1 << 56) - 1)] = -1
    return gone


# ---------------------------------------------------------------------------- seal
def seal_step(world: Any, step: int, t0: int, t1: int, exported: bool,
              id_bases: dict[str, int], *,
              law_tables: frozenset[str] = frozenset()) -> SealedStep:
    """Seal the step `[t0, t1)` that `rounds.run_step` just ran (see the module docstring).

    `id_bases` (one base per namespace `<ns>` and per event table `event:<name>`) is advanced in
    place by the rows this step numbers.
    """
    from neorisk_simkit.checks.structural import check_step

    plan, seed = world.plan, world.seed
    world.flush_all()
    counted = int(world.step_rows)        # everything the step cap counts, p.ids included (D41)
    chunks = world.take_chunks()
    accumulators = world.take_accumulators()
    specs = buffer_specs(plan)
    records = {s.name: _merge(chunks, s) for s in specs if s.kind != "create"}
    creates = {s.name: _merge(chunks, s) for s in specs if s.kind == "create"}

    # 2. dense indices per namespace
    owner_ptype = {p.table: p.ptype_code for p in plan.partitions if p.kind == "owner"}
    dense_of: dict[str, np.ndarray] = {}
    pids = []
    for ns in plan.namespaces:
        rows = creates[ns]
        base = id_bases.get(ns, 0)
        d = assign_dense(rows["pid"], rows["ordinal"], base)
        id_bases[ns] = base + len(d)
        dense_of[ns] = d
        pt = owner_ptype.get(ns)
        pids.append((np.int64(pt) << np.int64(56)) | d if pt is not None else d)
    if plan.namespaces:
        remap = _Remap(np.concatenate([creates[ns]["handle"] for ns in plan.namespaces]),
                       np.concatenate([dense_of[ns] for ns in plan.namespaces]),
                       np.concatenate(pids))
    else:
        z = np.zeros(0, np.int64)
        remap = _Remap(z, z, z)

    # 3. remap provisional handles
    for e in plan.events:
        rows = records[e.name]
        for c in e.cols[len(COMMON_COLUMNS):]:
            if c.ltype.kind == "ref":
                remap.apply(rows[c.name], f"event {e.name}.{c.name}")
        remap.apply(rows["pid"], f"partition_id of event {e.name}", pid=True)
    for g in plan.change_groups:
        rows = records[g.name]
        for c in g.cols:
            if c.ltype.kind == "ref":
                remap.apply(rows[c.name], f"history {g.name}.{c.name}")
        remap.apply(rows["entity_id"], f"entity_id of history {g.name}")
        remap.apply(rows["pid"], f"partition_id of history {g.name}", pid=True)
    tables = {t.name: t for t in plan.tables}
    for ns in plan.namespaces:
        for c in (tables[ns].cols if ns in tables else ()):
            if c.ltype.kind == "ref":
                remap.apply(creates[ns][c.name], f"created {ns}.{c.name}")
    if exported:                                 # D48: dense range check, before public IDs
        from neorisk_simkit.checks.structural import check_refs, ref_bounds
        n_refs = check_refs(plan, records, creates, ref_bounds(world, id_bases))
    owners = _remap_world(world, remap)

    # 4. free retired slots
    freed = _free_retired(world, owners)

    # 7. output size (the step cap itself is enforced as slabs are flushed: `World._flush`);
    # `rows` = records + created entity rows (warm-up included); `counted_rows` (rows plus
    # `p.ids` allocations, what the cap counts) drives the step length (D41)
    entity_ns = [ns for ns in plan.namespaces if ns in tables]
    parts = [*records.values(), *(creates[ns] for ns in entity_ns)]
    n_rows = sum(len(next(iter(p.values()))) for p in parts)
    n_bytes = sum(a.nbytes for p in parts for a in p.values())

    # 8. (F-01) a warm-up step keeps the rows the laws read, before `keep` drops them
    warmup_rows = {} if exported else {
        e.name: event_table(e, records[e.name], dict(id_bases), seed)
        for e in plan.events if e.name in law_tables}

    # 5, 6, 8. events, postings and history (warm-up steps drop their rows), entities always
    def keep(rows: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        return rows if exported else {k: v[:0] for k, v in rows.items()}

    records_out = {e.name: event_table(e, keep(records[e.name]), id_bases, seed)
                   for e in plan.events}
    events = {e.name: records_out[e.name] for e in plan.events if e.group == "events"}
    postings = {e.name: records_out[e.name] for e in plan.events if e.group == "postings"}
    history = {g.name: history_table(g, keep(records[g.name]), seed)
               for g in plan.change_groups}
    entities = {ns: entity_table(ns, tables[ns].cols, dense_of[ns], creates[ns]["created_at"],
                                 ORIGIN_CREATED, creates[ns], seed) for ns in entity_ns}
    stats = {"rows": int(n_rows), "counted_rows": counted, "bytes": int(n_bytes),
             "freed_slots": len(freed),
             "events": {k: t.num_rows for k, t in events.items()},
             "postings": {k: t.num_rows for k, t in postings.items()},
             "history": {k: t.num_rows for k, t in history.items()},
             "entities": {k: t.num_rows for k, t in entities.items()}}
    sealed = SealedStep(int(step), int(t0), int(t1), bool(exported), events, history, entities,
                        stats, postings=postings, accumulators=accumulators,
                        warmup_rows=warmup_rows, retired=freed)
    if exported:
        stats["checks"] = check_step(sealed, plan)                # 9.
        stats["checks"]["ref_in_range"] = n_refs
    return sealed
