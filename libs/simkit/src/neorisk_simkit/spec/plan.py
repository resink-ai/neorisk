"""The normalized plan a run executes: a pack, its overlays and stable ids for every action."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from neorisk_simkit.spec.pack import Action, CheckSpec, Kind, Pack, Source, Table

NS_SPAN = 1_000_000_000          # ids of namespace k are k * NS_SPAN + 1, + 2, ...


@dataclass
class Plan:
    pack: Pack
    overlays: list[Any] = field(default_factory=list)   # applied spec.overlay.Overlay objects
    sources: list[tuple[Source, int]] = field(default_factory=list)   # (source, namespace)
    actions: list[Action] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.pack.name

    @property
    def kinds(self) -> dict[str, Kind]:
        return self.pack.kinds

    @property
    def events(self) -> dict[str, Table]:
        return self.pack.events

    @property
    def entities(self) -> dict[str, Table]:
        return self.pack.entities

    @property
    def checks(self) -> list[CheckSpec]:
        return self.pack.checks + [c for o in self.overlays for c in o.checks]

    def namespace(self, overlay: str | None) -> int:
        if overlay is None:
            return 0
        return 1 + [o.name for o in self.overlays].index(overlay)


def build_plan(pack: Pack, overlays: list[Any] = ()) -> Plan:
    """Freeze `pack` (overlays already applied to it) into a plan with action ids."""
    plan = Plan(pack, list(overlays))
    plan.sources = [(s, 0) for s in pack.sources]
    for i, o in enumerate(plan.overlays, start=1):
        plan.sources += [(s, i) for s in o.sources]
    for k in pack.kinds.values():
        for a in k.actions.values():
            a.id = len(plan.actions)
            plan.actions.append(a)
    return plan


def validate(plan: Plan) -> list[str]:
    """Structural contradictions only (§16): bad boundaries, unbounded spawns, schema errors."""
    errs: list[str] = []
    tables = {**plan.entities, **plan.events}
    for t in tables.values():
        for c, lt in t.columns().items():
            if lt.kind == "ref" and lt.target not in plan.entities:
                errs.append(f"{t.name}.{c}: ref to unknown entity table {lt.target!r}")
        if t.kind == "entity" and t.key in t.cols:
            errs.append(f"{t.name}: key {t.key!r} is declared again as a column")
    for k in plan.kinds.values():
        if not k.latency.min > 0:
            errs.append(f"{k.name}: boundary latency δ must be > 0 (got {k.latency.min})")
        if k.latency.hi < k.latency.min:
            errs.append(f"{k.name}: latency max {k.latency.hi} < min {k.latency.min}")
        if not k.actions:
            errs.append(f"{k.name}: no actions")
        for p in k.processes.values():
            if p.start is not None and p.start not in k.actions:
                errs.append(f"{k.name}.{p.name}: start action {p.start!r} is not defined")
            if not isinstance(p.max_spawn_depth, int) or not 0 <= p.max_spawn_depth <= 16:
                errs.append(f"{k.name}.{p.name}: max_spawn_depth must be an int in [0, 16]")
    for o in plan.overlays:
        errs += o.problems(plan)
    return errs
