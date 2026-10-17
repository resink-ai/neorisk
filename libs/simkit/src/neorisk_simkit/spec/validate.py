"""Structural validation of a resolved run (no simulation)."""

from __future__ import annotations

from dataclasses import dataclass, field

from neorisk_simkit.engine.abi import START
from neorisk_simkit.engine.identity import MAX_NAMESPACES, NS_BITS
from neorisk_simkit.spec.caps import (
    OUTBOX_ROW_BYTES,
    BudgetError,
    CapItem,
    check_budget,
    compute_caps,
    record_row_bytes,
)
from neorisk_simkit.spec.types import storage_dtype


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


# D43: a created owner's initial state rides the user columns 0..6 of its creation message
CREATION_PAYLOAD_COLS = 7


def _owner_tables(plan) -> dict[str, str]:
    """Owner table -> owner partition name."""
    return {p.table: p.name for p in plan.partitions if p.kind == "owner" and p.table}


def creation_graph(plan) -> dict[str, list[tuple[str, str]]]:
    """Owner-creation edges (D42): partition -> [(created owner partition, process)], every
    partition in plan order, edges in process order."""
    owner_of = _owner_tables(plan)
    graph: dict[str, list[tuple[str, str]]] = {p.name: [] for p in plan.partitions}
    for p in plan.processes:
        for ns in p.kernel.max.creates:
            if ns in owner_of:
                graph[p.partition].append((owner_of[ns], p.name))
    return graph


def _creation_cycle(graph: dict[str, list[tuple[str, str]]]) -> tuple[list[str], list[str]]:
    """The first creation cycle a depth-first search in plan order finds, as (partitions on it,
    closing with the first again; processes on its edges); empty lists when acyclic."""
    done: set[str] = set()
    path: list[str] = []                              # partitions on the DFS stack
    via: list[str] = []                               # via[i]: process of edge path[i] -> path[i+1]

    def visit(n: str) -> tuple[list[str], list[str]] | None:
        path.append(n)
        for dst, proc in graph[n]:
            via.append(proc)
            if dst in path:
                i = path.index(dst)
                return [*path[i:], dst], via[i:]
            if dst not in done:
                found = visit(dst)
                if found:
                    return found
            via.pop()
        path.pop()
        done.add(n)
        return None

    for n in graph:
        if n not in done:
            found = visit(n)
            if found:
                return found
    return [], []


def _longest_spawn_chain(graph: dict[str, list[tuple[str, str]]]) -> list[str]:
    """Processes along the longest creation chain of an acyclic graph (first in plan order on
    ties); its length is the static spawn depth."""
    memo: dict[str, list[str]] = {}

    def chain(n: str) -> list[str]:
        if n not in memo:
            best: list[str] = []
            for dst, proc in graph[n]:
                c = [proc, *chain(dst)]
                if len(c) > len(best):
                    best = c
            memo[n] = best
        return memo[n]

    best: list[str] = []
    for n in graph:
        if len(chain(n)) > len(best):
            best = chain(n)
    return best


def _spawn_errors(run) -> list[str]:
    graph = creation_graph(run.plan)
    parts, procs = _creation_cycle(graph)
    if parts:
        return [(f"unbounded spawn: owner creation cycle {' -> '.join(parts)} "
                 f"(processes {', '.join(procs)})")]
    chain = _longest_spawn_chain(graph)
    m = run.budget.max_spawn_depth
    if len(chain) > m >= 1:
        return [(f"spawn depth {len(chain)} exceeds budget.max_spawn_depth {m} "
                 f"(processes {' -> '.join(chain)})")]
    return []


def _law_reason(plan, law) -> str | None:
    """Why a declared law cannot be evaluated (D47), or None."""
    from neorisk_simkit.checks.laws import resolve_path

    events = {e.name: {c.name: c.ltype for c in e.cols} for e in plan.events}

    def event_cols(name: str, cols) -> str | None:
        if name not in events:
            return f"unknown event or posting table '{name}'"
        missing = [c for c in cols if c not in events[name]]
        return f"{name} has no column {missing[0]}" if missing else None

    def event_path(path: str) -> str | None:
        try:
            kind = resolve_path(plan, path)[0]
        except ValueError as e:
            return str(e)
        return None if kind == "event" else f"{path!r} is not an event or posting column"

    k = law.kind
    if k == "never_negative":
        try:
            resolve_path(plan, law.arg("path"))
        except ValueError as e:
            return str(e)
        return None
    if k == "total_le":
        return event_path(law.arg("lhs"))
    if k == "sum_le":
        return event_path(law.arg("lhs")) or event_path(law.arg("rhs"))
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
        elif part_kind.get(b.frm) == "owner" and part_kind.get(b.to) == "owner":
            errs.append(f"boundary {b.name}: owner-to-owner messages arrive in M3")
        elif part_kind.get(b.frm) != "owner":
            errs.append(f"boundary {b.name}: messages go from an owner to a shard")

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
    errs += _spawn_errors(run)

    slab_rows = {n: eng.slab_bytes // max(1, rb) for n, rb in row_bytes.items()}
    forced_timers = eng.force_capacity.get("timers")
    outbox_cap = eng.force_capacity.get("requests", eng.slab_bytes // OUTBOX_ROW_BYTES)
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
        n_create = sum(k.max.creates.get(t, 0) for t in owner_tables)
        if n_create > 0 and k.max.requests + n_create > outbox_cap:
            errs.append(f"{p.name}: declared maximum of requests {k.max.requests} plus "
                        f"{n_create} creation message(s) exceeds the outbox capacity "
                        f"{outbox_cap}")
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
