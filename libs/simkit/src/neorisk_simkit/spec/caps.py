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


def row_bytes(cols: Iterable[Column]) -> int:
    return sum(storage_dtype(c.ltype).itemsize + (1 if c.ltype.nullable else 0) for c in cols)


def slabs_per_worker(plan: Plan) -> int:
    return len(plan.events) + len(plan.change_groups) + len(plan.namespaces) + 1


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
    for pop in plan.populations:                 # tables built by a recipe (std.devices, ...)
        for r in pop.refs.values():
            bound = r.max_table_rows(name, pop.n) if hasattr(r, "max_table_rows") else None
            if bound is not None:
                return int(bound)
    return 0


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
        "output_slabs": (workers * slabs_per_worker(plan) * eng.slab_bytes, ""),
        "step_output": (step, "estimate is 25% of the cap (adaptive target)"),
        "merge_working_space": (2 * step, ""),
        "live_partition_state": (_live_state(plan), ""),
        "timer_heaps": (eng.timer_nodes * NODE_BYTES, ""),
        "requests_and_inboxes": (eng.max_messages_per_step * OUTBOX_ROW_BYTES
                                 + eng.payload_slots * 8 * PAYLOAD_W, ""),
        "fanout_bursts": (sum(p.kernel.substep * max_row for p in plan.processes
                              if p.kernel.substep), ""),
        "read_inputs": (read, ""),
        "checker_state": (0, "not used in S1"),
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
