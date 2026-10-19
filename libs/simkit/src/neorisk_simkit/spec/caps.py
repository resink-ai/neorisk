"""Memory caps (spec section 10): per-item hard cap and estimate, and the budget check."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from neorisk_simkit.engine import cmdq as _cmdq
from neorisk_simkit.spec.plan import Column, Plan
from neorisk_simkit.spec.types import storage_dtype

CAP_ITEMS = ("output_slabs", "step_output", "merge_working_space", "live_partition_state",
             "timer_heaps", "requests_and_inboxes", "fanout_bursts", "read_inputs",
             "checker_state", "scorer", "entity_buffers")

# D8 (amended by D61: the sender key): bytes per command node, from the node pool's own field
# table (spec section 10 says 24 B); memory caps use the real size.
NODE_BYTES = _cmdq.NODE_BYTES
PAYLOAD_W = _cmdq.PAYLOAD_W
OUTBOX_ROW_BYTES = 8 * 12 + 8 * PAYLOAD_W
_LOCAL_TYPE_BYTES = {"i8": 1, "u8": 1, "i16": 2, "i32": 4, "u32": 4, "i64": 8, "f64": 8, "ref": 8}
_ORDERING_COLS_BYTES = 5 * 8        # entity_id, valid_from, lamport, partition_id, seq


def sum_le_on_state(lw, plan) -> bool:
    """Whether a `sum_le` law's right side is an owner table column (D81), not an event."""
    from neorisk_simkit.checks.laws import resolve_path  # checks imports this module

    try:
        return resolve_path(plan, lw.arg("rhs"))[0] == "owner"
    except ValueError:
        return False


def law_key_bytes(lw, plan: Plan | None = None) -> int:
    """Bytes a keyed law's reducer carries per key, from its real layout (spec section 10:
    keyed aggregates x bytes per key; D47). `checks.laws` charges exactly these sizes."""
    if lw.kind == "at_most_once":
        n = len(lw.arg("key"))
        return 8 if n == 1 else 8 * (1 + n)   # the value; or the hash index plus every column
    if lw.kind == "sum_le":
        return 3 * 8                          # key, sum of lhs, sum of rhs (or the rhs state
                                              # value last seen: one key array serves both)
    if lw.kind == "resolved":
        return 7 * 8                          # key, opened at, deadline, pid, seq, action, warm
    if lw.kind == "lifecycle":
        return 2 * 8                          # key, last listed table code (int64)
    return 0                                  # total_le (with or without per): one total


RESOLVED_CHUNK = 1 << 16            # `resolved` matches its open keys in chunks of this many
SUM_LE_STATE_PEAK = 58              # bytes per key, see `law_peak_bytes`


def law_peak_bytes(lw, keys: int, plan: Plan | None = None) -> int:  # plan: needed by sum_le
    """Peak bytes a keyed law holds while it updates its state to `keys` keys: the old and the
    new arrays live together, plus the update's own workspace (`checks.laws`; spec section 10
    `checker_state`). Upper bounds from the arrays the update keeps alive at once (measured
    with `tracemalloc` in `test_checks_laws_keyed` and `test_checks_laws_m3`); the step's own
    rows (a few arrays the size of the step) are not counted here:

    - `at_most_once`: `np.insert` builds the new key array (then the new column array) while
      the old one is alive, with a 1-byte mask per key: `2 x key bytes + 1` per key.
    - `sum_le`: three `np.insert`s (keys, then the two sums), each freeing its old array; the
      last holds the new keys and sums plus the old rhs and a mask: `8 x old + 25 x new`,
      at most 33 B per key.
    - `sum_le` against owner state (D81; needs `plan` to tell the forms apart): the seal's
      refresh reads every live and just-retired owner (each one a key after the update), so
      beside the 24 B state it holds per owner at most four 8-byte arrays at once (sorting
      the public IDs: IDs, values, the order and one sorted copy; the hit test and the state
      update run in chunks of `RESOLVED_CHUNK`); merging new keys holds the old and new
      arrays with one shared mask, as `sum_le` (33 B). Measured at most 56 B per key:
      `SUM_LE_STATE_PEAK` = 58 B per key.
    - `lifecycle`: like `at_most_once` with a 16 B key (key, last table code): `2 x 16 + 1`.
    - `resolved`: the open table grows one column at a time (each old column freed as it is
      replaced), is matched in chunks of `RESOLVED_CHUNK` keys and filtered one column at a
      time: the 56 B table, a 1-byte mask and one 8-byte column copy, rounded up to 66 B per
      key, plus 64 B per key of one chunk for the matching temporaries.
    """
    if lw.kind in ("at_most_once", "lifecycle"):
        return (2 * law_key_bytes(lw) + 1) * keys
    if lw.kind == "sum_le":
        if plan is None:                      # the two forms differ by 25 B/key (review M-1)
            raise ValueError("law_peak_bytes: a sum_le law needs the plan to tell its event "
                             "and owner-state forms apart (D81)")
        return (SUM_LE_STATE_PEAK if sum_le_on_state(lw, plan) else 33) * keys
    if lw.kind == "resolved":
        return 66 * keys + 64 * min(keys, RESOLVED_CHUNK)
    return 0


def checker_state_bytes(plan: Plan, max_keys: int) -> int:
    """`checker_state`: the largest peak any declared keyed law reaches at `max_keys` keys (0
    when none is declared). The laws share it: a law's update must fit beside the state the
    others carry (`checks.laws.LawBook`)."""
    return max((law_peak_bytes(c.law, max_keys, plan) for c in plan.checks), default=0)


@dataclass(frozen=True)
class CapItem:
    name: str
    hard_bytes: int
    estimate_bytes: int
    note: str


class BudgetError(Exception):
    pass


def hidden_bytes(plan: Plan) -> int:
    from neorisk_simkit.engine.world import hidden_bytes as world_hidden_bytes

    per_type: dict[str, int] = {}
    for p in plan.processes:
        per_type[p.partition] = per_type.get(p.partition, 0) + 1
    a = max(1, max(per_type.values(), default=1))
    return world_hidden_bytes(a, len(plan.namespaces))


def _cq_row_bytes() -> int:
    """Bytes per pending-creation queue row (D44)."""
    from neorisk_simkit.engine.admit import CreationQueue

    return CreationQueue.row_bytes


def row_bytes(cols: Iterable[Column]) -> int:
    return sum(storage_dtype(c.ltype).itemsize + (1 if c.ltype.nullable else 0) for c in cols)


def slabs_per_worker(plan: Plan) -> int:
    return len(plan.events) + len(plan.change_groups) + len(plan.namespaces) + 1


def clog_bytes(slab_bytes: int) -> int:
    """Bytes of one worker's commit log (D80): `engine.slabs.clog_rows` rows of 5 int64."""
    from neorisk_simkit.engine.slabs import CLOG_ROW_BYTES, clog_rows  # engine imports spec
    return clog_rows(slab_bytes) * CLOG_ROW_BYTES


def record_row_bytes(plan: Plan) -> dict[str, int]:
    """Row bytes of every record table a kernel can reserve: events and change-group histories."""
    out = {e.name: row_bytes(e.cols) for e in plan.events}
    for g in plan.change_groups:
        out[g.name] = row_bytes(g.cols) + _ORDERING_COLS_BYTES
    return out


def _table_rows(plan: Plan, name: str) -> int:
    for pop in plan.populations:
        if pop.table == name:
            return pop.n
    t = plan.table(name)
    if t.source is not None and t.source.n is not None:
        return t.source.n
    total = 0                                    # tables built by recipes (std.devices, ...):
    for pop in plan.populations:                 # a cohort's recipe appends rows (D94)
        for r in pop.refs.values():
            bound = r.max_table_rows(name, pop.n) if hasattr(r, "max_table_rows") else None
            if bound is not None:
                total += int(bound)
    return total


def _csr_entries(recipe, n_owners: int) -> int:
    """int64 entries of a population refs CSR: the recipe's bound, else 3 per owner."""
    if hasattr(recipe, "max_csr_entries"):
        return int(recipe.max_csr_entries(n_owners))
    return 3 * n_owners


def _extra_read_bytes(plan: Plan, table: str) -> int:
    """Engine-added read columns of `table`: recipe columns, `local_index`, `cumw` (8 B each)."""
    from neorisk_simkit.engine.layout import _recipes

    n_cols = sum(len(r.read_column_names(table)) for r in _recipes(plan))
    n_cols += any(p.items == table for p in plan.partitions)
    t = plan.table(table)
    n_cols += t.source is not None and getattr(t.source, "weight", None) is not None
    return 8 * n_cols * _table_rows(plan, table)


def _local_bytes(local) -> int:
    if local is None:
        return 0
    return sum(_LOCAL_TYPE_BYTES[t] * n for t, n in local.fields.values())


def _state_item_bytes(decl: str) -> tuple[int, str | None]:
    base, _, rest = decl.partition("[")
    return int(np.dtype(_STATE_NP[base]).itemsize), (rest[:-1] if rest else None)


_STATE_NP = {"i8": "int8", "u8": "uint8", "i16": "int16", "i32": "int32", "u32": "uint32",
             "i64": "int64", "f64": "float64", "ref": "int64", "bool": "uint8"}


def _live_state(plan: Plan) -> int:
    hid = hidden_bytes(plan)
    total = 0
    for part in plan.partitions:
        if part.kind == "owner":
            local = sum(_local_bytes(p.kernel.local) for p in plan.processes
                        if p.partition == part.name)
            total += part.max_live * (row_bytes(plan.table(part.table).cols) + local + hid)
        else:
            total += part.n * hid
            total += part.n * sum(_local_bytes(p.kernel.local) for p in plan.processes
                                  if p.partition == part.name)
            for decl in part.state.values():
                width, items = _state_item_bytes(decl)
                total += width * (_table_rows(plan, items) if items else part.n)
    return total


# Arrow bytes per row of an entity column (text is always written null: offsets only)
_ARROW_BYTES = {"cat": 2, "ts": 8, "bool": 1, "text": 4, "f64": 8, "i16": 2, "i32": 4}
_ORIGIN_MAX = max(len(o) for o in ("static", "initial", "arrival", "created"))


def entity_row_bytes(plan: Plan, table: str) -> int:
    """Upper bound of the Arrow bytes one buffered entity row costs: `id`, `created_at`,
    `origin` (offset + longest label), every column's width, one validity byte per column, and
    per-chunk overhead (string offsets end, category dictionaries) charged to every row, since
    the writer never buffers an empty chunk."""
    cols = plan.table(table).cols
    per_row = 8 + 8 + 4 + _ORIGIN_MAX + 3
    per_chunk = 4                                     # origin offsets end
    for c in cols:
        per_row += _ARROW_BYTES.get(c.ltype.kind, 8) + 1
        if c.ltype.kind == "text":
            per_chunk += 4
        if c.ltype.kind == "cat":
            per_chunk += 4 * (len(c.ltype.values) + 1) + sum(len(str(v).encode())
                                                             for v in c.ltype.values)
    return per_row + per_chunk


def entity_buffer_bytes(plan: Plan, row_group_rows: int) -> tuple[int, int]:
    """(pending, working) bytes of the streaming entity writer (`io.entities`): every table keeps
    at most `row_group_rows - 1` rows buffered across steps (fewer when the table's row count
    is fixed and smaller), and writing one row group needs about twice its size. Bytes are
    logical Arrow bytes (`Table.nbytes`), not allocator capacity or padding."""
    pending = biggest = 0
    group = max(1, int(row_group_rows))
    for t in plan.tables:
        rows = group - 1
        n = _table_rows(plan, t.name)
        if t.name not in plan.namespaces and n:
            rows = min(rows, n)
        rb = entity_row_bytes(plan, t.name)
        pending += rows * rb
        biggest = max(biggest, min(group, rows + 1) * rb)
    return pending, 2 * biggest


def _owner_message_bytes(plan, eng) -> int:
    """The carried owner-to-owner message buffer (D73): `max_owner_messages_per_step` rows of
    the outbox columns and a payload row (`OUTBOX_ROW_BYTES`) plus the six D61 sender-key
    parts and the cause event id (D80); 0 without such boundaries (the world then allocates
    one row)."""
    if not any(b.o2o for b in plan.boundaries):
        return 0
    return eng.max_owner_messages_per_step * (OUTBOX_ROW_BYTES + 7 * 8)


def compute_caps(run, threads: int | None = None) -> list[CapItem]:
    """Every item's hard cap and estimate for `threads` workers (default `budget.threads`)."""
    plan, eng, bud = run.plan, run.engine, run.budget
    workers = bud.threads if threads is None else int(threads)
    rb = record_row_bytes(plan)
    max_row = max(rb.values(), default=0)

    step_rows_bytes = bud.max_step_rows * max_row
    step = min(step_rows_bytes, bud.max_step_bytes) if bud.max_step_bytes else step_rows_bytes

    read_tables = {t for p in plan.processes for t in p.reads.values()}
    read = sum(_table_rows(plan, t) * row_bytes(plan.table(t).cols) + _extra_read_bytes(plan, t)
               for t in read_tables)
    read += sum(8 * _csr_entries(r, pop.n) for pop in plan.populations
                for r in pop.refs.values())

    items = {
        "output_slabs": (workers * slabs_per_worker(plan) * eng.slab_bytes
                         + workers * clog_bytes(eng.slab_bytes), ""),
        "step_output": (step, "estimate is 25% of the cap (adaptive target)"),
        "merge_working_space": (2 * step, ""),
        "live_partition_state": (_live_state(plan), ""),
        "timer_heaps": (eng.timer_nodes * NODE_BYTES, ""),
        "requests_and_inboxes": (eng.max_messages_per_step * OUTBOX_ROW_BYTES
                                 + eng.payload_slots * 8 * PAYLOAD_W
                                 + bud.max_admissions_per_step * _cq_row_bytes()
                                 + _owner_message_bytes(plan, eng), ""),
        "fanout_bursts": (sum(p.kernel.substep * max_row for p in plan.processes
                              if p.kernel.substep), ""),
        "read_inputs": (read, ""),
        "checker_state": (checker_state_bytes(plan, bud.max_checker_keys),
                          "peak update bytes of the widest keyed law at max_checker_keys (D47)"),
        "scorer": (0, "not used in S1"),
        "entity_buffers": (sum(entity_buffer_bytes(plan, run.writer.row_group_rows)),
                           "row groups buffered by the entity writer, plus one being written"),
    }
    caps = []
    for name in CAP_ITEMS:
        hard, note = items[name]
        est = hard // 4 if name == "step_output" else hard
        caps.append(CapItem(name, hard, est, note))
    return caps


def check_budget(caps: list[CapItem], budget) -> None:
    total = sum(c.hard_bytes for c in caps)
    if total <= budget.memory_bytes:
        return
    mib = 1024 * 1024
    listing = ", ".join(f"{c.name}={c.hard_bytes / mib:.1f} MiB"
                        for c in sorted(caps, key=lambda c: -c.hard_bytes))
    raise BudgetError(f"memory caps exceed the memory budget ({total / mib:.1f} MiB > "
                      f"{budget.memory_bytes / mib:.1f} MiB): {listing}")
