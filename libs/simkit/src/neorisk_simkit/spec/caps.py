"""Memory caps (spec section 10): per-item hard cap and estimate, and the budget check."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from neorisk_simkit.spec.plan import Column, Plan
from neorisk_simkit.spec.types import storage_dtype

CAP_ITEMS = ("output_slabs", "step_output", "merge_working_space", "live_partition_state",
             "timer_heaps", "requests_and_inboxes", "fanout_bursts", "read_inputs",
             "checker_state", "scorer")

# D8: 40 B per command node (spec section 10 says 24 B); memory caps use the real size.
NODE_BYTES = 40
# engine.cmdq does not exist yet; Task 7's test asserts these match cmdq.PAYLOAD_W.
PAYLOAD_W = 12
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
    return t.source.n if t.source is not None and t.source.n is not None else 0


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
            for decl in part.state.values():
                width, items = _state_item_bytes(decl)
                total += width * (_table_rows(plan, items) if items else part.n)
    return total


def compute_caps(run) -> list[CapItem]:
    plan, eng, bud = run.plan, run.engine, run.budget
    rb = record_row_bytes(plan)
    max_row = max(rb.values(), default=0)

    step_rows_bytes = bud.max_step_rows * max_row
    step = min(step_rows_bytes, bud.max_step_bytes) if bud.max_step_bytes else step_rows_bytes

    read_tables = {t for p in plan.processes for t in p.reads.values()}
    read = sum(_table_rows(plan, t) * row_bytes(plan.table(t).cols) for t in read_tables)
    read += sum(pop.n * 3 * 8 for pop in plan.populations if pop.refs)

    items = {
        "output_slabs": (bud.threads * slabs_per_worker(plan) * eng.slab_bytes, ""),
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
