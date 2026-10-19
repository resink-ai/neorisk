"""Structural validation of a resolved run (no simulation)."""

from __future__ import annotations

from dataclasses import dataclass, field

from neorisk_simkit.engine.abi import START
from neorisk_simkit.engine.identity import MAX_NAMESPACES, NS_BITS
from neorisk_simkit.io.seal import ENTITY_HEAD, HISTORY_HEAD
from neorisk_simkit.spec.caps import (
    OUTBOX_ROW_BYTES,
    BudgetError,
    CapItem,
    check_budget,
    compute_caps,
    record_row_bytes,
)
from neorisk_simkit.spec.types import COMMON_COLUMNS, storage_dtype


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    caps: list[CapItem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _narrow_int(t) -> bool:
    dt = storage_dtype(t)
    return dt.kind in "iu" and dt.itemsize < 8


# D72: the hidden per-slot `depth` is uint8 and a machine instance's `dep` is i8 (D63), whose
# default is budget.max_spawn_depth; a larger limit would let the stored depth wrap
MAX_SPAWN_DEPTH = 127

# D43: a created owner's initial state rides the user columns 0..6 of its creation message
CREATION_PAYLOAD_COLS = 7


def _owner_tables(plan) -> dict[str, str]:
    """Owner table -> owner partition name."""
    return {p.table: p.name for p in plan.partitions if p.kind == "owner" and p.table}


def _law_reason(plan, law) -> str | None:
    """Why a declared law cannot be evaluated (D47), or None."""
    from neorisk_simkit.checks.laws import resolve_path

    events = {e.name: {c.name: c.ltype for c in e.cols} for e in plan.events}
    labels = {e.name for e in plan.events if e.group == "labels"}

    def label(name: str) -> str | None:
        # F-24: `LawBook` reads events and postings only
        return f"label table {name} cannot be checked by a law" if name in labels else None

    def event_cols(name: str, cols) -> str | None:
        if (r := label(name)) is not None:
            return r
        if name not in events:
            return f"unknown event or posting table '{name}'"
        missing = [c for c in cols if c not in events[name]]
        return f"{name} has no column {missing[0]}" if missing else None

    def event_path(path: str) -> str | None:
        try:
            kind, table, _ = resolve_path(plan, path)
        except ValueError as e:
            return str(e)
        if kind == "event" and (r := label(table)) is not None:
            return r
        return None if kind == "event" else f"{path!r} is not an event or posting column"

    def state_rhs(lhs: str, rhs: str, by: str) -> str | None:
        """D81: `sum_le` against `<owner table>.<column>`, keyed by that table's key."""
        _, part, col = resolve_path(plan, rhs)
        table = plan.partition(part).table
        t = plan.table(table)
        if by != t.key:
            return f"sum_le against {rhs}: by must be {table}'s key {t.key}, not {by}"
        lt = next(c.ltype for c in t.cols if c.name == col)
        if lt.kind == "ref" or storage_dtype(lt).kind not in "iu":
            return f"sum_le against {rhs}: {table}.{col} must be an integer column"
        ltab = resolve_path(plan, lhs)[1]
        key = events[ltab].get(by)
        if key is None:
            return f"{ltab} has no column {by}"
        if key.kind != "ref" or key.target != table:
            return f"sum_le against {rhs}: {ltab}.{by} must be a ref to {table}"
        return None

    k = law.kind
    if k == "never_negative":
        try:
            kind, table, _ = resolve_path(plan, law.arg("path"))
        except ValueError as e:
            return str(e)
        return label(table) if kind == "event" else None
    if k == "total_le":
        per = law.get("per")
        if per is not None:
            from neorisk_simkit.spec.project import ProjectError, parse_duration

            try:
                ok = parse_duration(per) > 0
            except ProjectError:
                ok = False
            if not ok:
                return f"total_le per={per!r} must be a positive duration"
        return event_path(law.arg("lhs"))
    if k == "sum_le":
        if (r := event_path(law.arg("lhs"))) is not None:
            return r
        try:
            if resolve_path(plan, law.arg("rhs"))[0] == "owner":
                return state_rhs(law.arg("lhs"), law.arg("rhs"), law.arg("by"))
        except ValueError as e:
            return str(e)
        return event_path(law.arg("rhs"))
    if k == "lifecycle":
        edges = law.arg("edges")
        if not edges:
            return "lifecycle needs at least one edge"
        names = sorted({a for a, _ in edges} | {b for _, bs in edges for b in bs})
        key = (law.arg("key"),)
        return next((r for r in (event_cols(n, key) for n in names) if r), None)
    if k == "at_most_once":
        return event_cols(law.arg("event"), law.arg("key"))
    if k == "resolved":
        key = (law.arg("key"),)
        return next((r for r in (event_cols(e, key) for e in (law.arg("event"), *law.arg("by")))
                     if r), None)
    if k == "balanced":
        t = law.arg("table")
        bad = event_cols(t, (law.arg("amount"), law.arg("side"), *law.arg("by")))
        if bad:
            return bad
        side = events[t][law.arg("side")]
        if side.kind != "cat" or not {"debit", "credit"} <= set(side.values):
            return f"{t}.{law.arg('side')} must be a cat holding 'debit' and 'credit'"
        return None
    return f"unknown law {k!r}"


def _shadow_errors(plan) -> list[str]:
    """User columns named like a reserved head column the writer puts first: the output would
    hold two columns of that name, which parquet readers and SQL refuse."""
    errs = []
    entity, history = set(ENTITY_HEAD), set(HISTORY_HEAD)
    common = {n for n, _ in COMMON_COLUMNS}
    for t in plan.tables:
        errs += [f"table {t.name}: column {c.name!r} shadows the reserved entity column "
                 f"{c.name!r} (entities/ write {', '.join(ENTITY_HEAD)} first)"
                 for c in t.cols if c.name in entity]
    for e in plan.events:
        what = {"postings": "posting", "labels": "label"}.get(e.group, "event")
        errs += [f"{what} {e.name}: column {c.name!r} shadows the reserved common column "
                 f"{c.name!r}" for c in e.cols[len(COMMON_COLUMNS):] if c.name in common]
    for g in plan.change_groups:
        errs += [f"change group {g.name}: column {c.name!r} shadows the reserved history "
                 f"column {c.name!r}" for c in g.cols if c.name in history]
    return errs


def _law_errors(plan) -> list[str]:
    return [f"check {c.id}: {r}" for c in plan.checks
            if (r := _law_reason(plan, c.law)) is not None]


def validate(run, threads: int | None = None) -> ValidationReport:
    """Every structural error of `run`, and its caps for `threads` workers (default
    `budget.threads`; pass the worker count the run will allocate)."""
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
        elif b.o2o:
            if b.min_latency_us < eng.step_max_us:
                errs.append(f"boundary {b.name}: owner-to-owner messages need a minimum latency "
                            f">= engine.step_max ({eng.step_max_us} us)")
            target = plan.partition(b.to)
            if not any(pop.table == target.table for pop in plan.populations):
                errs.append(f"boundary {b.name}: owner-to-owner messages need a target partition "
                            "with a population")
        elif part_kind.get(b.frm) != "owner":
            errs.append(f"boundary {b.name}: messages go from an owner to a shard")

    populated = {pop.table for pop in plan.populations}
    for t in plan.member_tables:
        if t not in populated or plan.table(t).creatable:
            # D75: member IDs follow the population; a created table would share its namespace
            # with created owners, whose rows member rows could not be told from
            errs.append(f"member table {t}: an owner acting for its partition needs a "
                        f"population of {t!r} and no created rows (child_of)")

    for e in plan.events:
        for c in e.cols[8:]:                      # after the common columns
            if c.ltype.kind == "text" and not c.ltype.nullable:
                errs.append(f"event {e.name}: column {c.name} is text; "
                            "S1 kernels can only write opt(text)")

    owner_tables = _owner_tables(plan)
    for t in plan.tables:
        if t.name not in owner_tables:
            continue
        for c in t.cols:
            if c.ltype.nullable and _narrow_int(c.ltype):
                errs.append(f"{t.name}.{c.name}: nullable {c.ltype.kind} state is not "
                            "supported; use opt(i64)")
        if not t.creatable:
            continue
        if len(t.cols) > CREATION_PAYLOAD_COLS:
            errs.append(f"created owner table {t.name} has {len(t.cols)} columns; a creation "
                        f"message carries at most {CREATION_PAYLOAD_COLS}")
        bad = next((c for c in t.cols if c.ltype.kind in ("f64", "text")), None)
        if bad is not None:
            errs.append(f"created owner table {t.name}: column {bad.name} is {bad.ltype.kind}; "
                        "a creation message carries only int64 values")
    errs += _shadow_errors(plan)

    slab_rows = {n: eng.slab_bytes // max(1, rb) for n, rb in row_bytes.items()}
    forced_timers = eng.force_capacity.get("timers")
    outbox_cap = eng.force_capacity.get("requests", eng.slab_bytes // OUTBOX_ROW_BYTES)
    for p in plan.processes:
        k = p.kernel
        if k.state != p.partition:
            errs.append(f"process {p.name} runs in partition '{p.partition}' "
                        f"but its kernel state is '{k.state}'")
        # D74: an owner acting for another may also write its records and send its boundaries
        acts = {p.partition, plan.partition(p.partition).acts_for} - {None}
        for name in k.max.records:
            if name not in record_owner:
                errs.append(f"{p.name} reserves unknown record type '{name}'")
            elif record_owner[name] not in acts:
                errs.append(f"{p.name} reserves records of '{name}' owned by partition "
                            f"'{record_owner[name]}'")
            elif k.max.records[name] > slab_rows[name]:
                errs.append(f"{p.name}: declared maximum of records of {name} "
                            "exceeds slab capacity")
        for local, b in (*p.requests.items(), *p.messages.items()):
            frm = plan.boundary(b).frm
            if frm not in acts:
                errs.append(f"{p.name} sends boundary '{b}' ({local}) from partition '{frm}', "
                            f"not its own")
        for name in k.max.creates:
            if name not in plan.namespaces:
                errs.append(f"{p.name} reserves unknown namespace '{name}'")
        n_create = sum(k.max.creates.get(t, 0) for t in owner_tables)
        if n_create > 0 and k.max.requests + n_create > outbox_cap:
            errs.append(f"{p.name}: declared maximum of requests {k.max.requests} plus "
                        f"{n_create} creation message(s) exceeds the outbox capacity "
                        f"{outbox_cap}")
        if p.max_spawn_depth is not None and p.max_spawn_depth < 1:
            errs.append(f"{p.name}: max_spawn_depth must be >= 1")
        if p.max_spawn_depth is not None and p.max_spawn_depth > MAX_SPAWN_DEPTH:
            errs.append(f"{p.name}: max_spawn_depth must be <= {MAX_SPAWN_DEPTH}")
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

    if len(plan.namespaces) > MAX_NAMESPACES:
        errs.append(f"{len(plan.namespaces)} id namespaces (created tables + p.ids) exceed the "
                    f"{MAX_NAMESPACES} that provisional handles can encode (D11: {NS_BITS} bits)")

    if run.budget.max_spawn_depth < 1:
        errs.append("budget.max_spawn_depth must be >= 1")
    if run.budget.max_spawn_depth > MAX_SPAWN_DEPTH:
        errs.append(f"budget.max_spawn_depth must be <= {MAX_SPAWN_DEPTH}")

    workers = run.budget.threads if threads is None else threads
    if workers < 1:
        errs.append(f"threads must be >= 1 (got {workers})")
        caps = compute_caps(run, 1)               # estimates only; the run is refused anyway
    else:
        caps = compute_caps(run, threads)
        try:
            check_budget(caps, run.budget)
        except BudgetError as e:
            errs.append(str(e))

    errs += _law_errors(plan)
    return ValidationReport(errs, warns, caps)
