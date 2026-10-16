"""Structural validation of a resolved run (no simulation)."""

from __future__ import annotations

from dataclasses import dataclass, field

from neorisk_simkit.engine.abi import START
from neorisk_simkit.spec.caps import (
    BudgetError,
    CapItem,
    check_budget,
    compute_caps,
    record_row_bytes,
)


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    caps: list[CapItem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(run) -> ValidationReport:
    plan, eng = run.plan, run.engine
    errs: list[str] = []
    warns: list[str] = []
    part_kind = {p.name: p.kind for p in plan.partitions}
    record_owner = {e.name: e.partition for e in plan.events}
    for g in plan.change_groups:
        record_owner[g.name] = next((p.name for p in plan.partitions if p.table == g.table), "")
    row_bytes = record_row_bytes(plan)

    for b in plan.boundaries:
        if b.min_latency_us <= 0:
            errs.append(f"boundary {b.name}: minimum latency must be > 0")
        if b.kind == "request":
            if part_kind.get(b.frm) != "owner" or part_kind.get(b.to) != "shard":
                errs.append(f"boundary {b.name}: requests go from an owner to a shard")
        elif part_kind.get(b.frm) == "owner" and part_kind.get(b.to) == "owner":
            errs.append(f"boundary {b.name}: owner-to-owner messages arrive in S2")
        elif part_kind.get(b.frm) != "owner":
            errs.append(f"boundary {b.name}: messages go from an owner to a shard")

    for e in plan.events:
        for c in e.cols[8:]:                      # after the common columns
            if c.ltype.kind == "text" and not c.ltype.nullable:
                errs.append(f"event {e.name}: column {c.name} is text; "
                            "S1 kernels can only write opt(text)")

    slab_rows = {n: eng.slab_bytes // max(1, rb) for n, rb in row_bytes.items()}
    forced_timers = eng.force_capacity.get("timers")
    for p in plan.processes:
        k = p.kernel
        if k.state != p.partition:
            errs.append(f"process {p.name} runs in partition '{p.partition}' "
                        f"but its kernel state is '{k.state}'")
        for name in k.max.records:
            if name not in record_owner:
                errs.append(f"{p.name} reserves unknown record type '{name}'")
            elif record_owner[name] != p.partition:
                errs.append(f"{p.name} reserves records of '{name}' owned by partition "
                            f"'{record_owner[name]}'")
            elif k.max.records[name] > slab_rows[name]:
                errs.append(f"{p.name}: declared maximum of records of {name} "
                            "exceeds slab capacity")
        for name in k.max.creates:
            if name not in plan.namespaces:
                errs.append(f"{p.name} reserves unknown namespace '{name}'")
        commands = set(p.commands) | set(k.commands)
        if p.every_us is not None and part_kind.get(p.partition) != "shard":
            errs.append(f"{p.name}: every= is only for shard processes (D26)")
        if START in commands and p.start is None and p.every_us is None:
            errs.append(f"{p.name} handles START but has no start= or every=")
        mapped = [(f"request {b}", c) for b, c in p.on_request.items()]
        mapped += [(f"response {b}.{r}", c) for (b, r), c in p.on_response.items()]
        mapped += [(f"message {b}", c) for b, c in p.on_message.items()]
        for what, c in mapped:
            if c not in commands:
                errs.append(f"{p.name} maps {what} to command {c} not listed in commands")
        if k.max.timers > eng.timer_nodes:
            errs.append(f"{p.name}: declared maximum of timers exceeds slab capacity")
        if forced_timers is not None and k.max.timers > forced_timers:
            errs.append(f"engine: force_capacity timers={forced_timers} is below the declared "
                        f"maximum timers={k.max.timers} of {p.name}")

    if run.budget.max_spawn_depth < 1:
        errs.append("budget.max_spawn_depth must be >= 1")

    caps = compute_caps(run)
    try:
        check_budget(caps, run.budget)
    except BudgetError as e:
        errs.append(str(e))

    if plan.checks:
        warns.append("checks declared but not evaluated until S2: "
                     + ", ".join(c.id for c in plan.checks))
    return ValidationReport(errs, warns, caps)
