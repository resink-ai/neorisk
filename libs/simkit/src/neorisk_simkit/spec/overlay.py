"""Behavior overlays (§08): a configurable group of actors with distinct behavior, added to an
existing pack without editing it. They emit the same event schema as everyone else.

    def apply(o: Overlay, size=4, ...):
        ring = o.cohort("hunter", kind="user", size=size, arrive=(0, 24),
                        suppress=["shopper"], redirect={"bonus_credited": "cash_out"})
        h = o.process("user", "hunting", cohort="hunter", start="hunt")

        @h.action
        def hunt(ctx, s, cmd):
            ctx.call("signup")              # base extension point, same atomic step
            ...

Contract:
- Size: `cohort(size= | share= | rate=)` with an arrival window; members get ids from the
  overlay's own namespace, so base ids never shift.
- Same schema: overlays cannot declare tables or columns. Rows come from base actions
  (`ctx.call`, or commands to base actions) and their own actions emitting base events.
- Different behavior: cohort members run the overlay's processes; `suppress` stops named base
  processes from starting for them; `redirect` routes a base command to an overlay action.
- Labels: `ctx.label(...)` rows with `label_available_at`, kept apart from events.
- Regression rule: see `checks.interference`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from neorisk_simkit.spec.pack import CheckSpec, Pack, PackError, Process, Source, _name


@dataclass
class Cohort:
    name: str
    kind: str
    ns: int
    overlay: str
    size: int | None = None
    share: float | None = None        # of the base partitions of `kind`
    rate: float | None = None         # arrivals per day (Poisson)
    arrive: tuple[float, float | None] = (0.0, None)   # (start day, span days)
    arrive_share: float | None = None  # or: span = this share of the run's days
    suppress: frozenset[str] = frozenset()
    redirect: dict[str, str] = field(default_factory=dict)
    init: dict[str, Any] = field(default_factory=dict)


class Overlay:
    def __init__(self, name: str, base: Pack, params: dict, ns: int):
        self.name, self.base, self.params, self.ns = name, base, dict(params), ns
        self.cohorts: list[Cohort] = []
        self.sources: list[Source] = []
        self.checks: list[CheckSpec] = []
        self.processes: list[Process] = []
        self._tables = (set(base.events), set(base.entities))

    def cohort(self, name: str, *, kind: str, size: int | None = None,
               share: float | None = None, rate: float | None = None,
               arrive: tuple[float, float | None] = (0.0, None),
               arrive_share: float | None = None, suppress: Iterable[str] = (),
               redirect: dict[str, str] | None = None, init: dict | None = None) -> Cohort:
        _name("cohort", name)
        if sum(x is not None for x in (size, share, rate)) > 1:
            raise PackError(f"cohort {name!r}: give one of size, share or rate")
        c = Cohort(name, kind, self.ns, self.name, size, share, rate, arrive, arrive_share,
                   frozenset(suppress), dict(redirect or {}), dict(init or {}))
        self.cohorts.append(c)
        if any(x is not None for x in (size, share, rate)):
            self.sources.append(_ArrivalSource(f"cohort_{name}", c))
        return c

    def process(self, kind: str, name: str, *, cohort: str, start: str | None = None,
                max_spawn_depth: int = 3, doc: str = "") -> Process:
        if kind not in self.base.kinds:
            raise PackError(f"overlay {self.name}: no partition kind {kind!r} in the base pack")
        p = self.base.kinds[kind].process(name, start=start, max_spawn_depth=max_spawn_depth,
                                          doc=doc)
        p.cohort = cohort
        self.processes.append(p)
        return p

    def source(self, fn: Callable | None = None, *, name: str | None = None):
        def reg(f: Callable) -> Callable:
            self.sources.append(Source(_name("source", name or f.__name__), f))
            return f
        return reg(fn) if fn is not None else reg

    def check(self, name: str, fn: Callable, *, group: str = "law", required: bool = True,
              doc: str = "") -> None:
        self.checks.append(CheckSpec(f"{self.name}.{name}", fn, group, required, doc))

    def problems(self, plan: Any) -> list[str]:
        errs = []
        if (set(self.base.events), set(self.base.entities)) != self._tables:
            errs.append(f"overlay {self.name}: overlays cannot add tables or columns")
        names = {c.name for c in self.cohorts}
        for c in self.cohorts:
            k = plan.kinds.get(c.kind)
            if k is None:
                errs.append(f"cohort {c.name}: unknown kind {c.kind!r}")
                continue
            for s in c.suppress - set(k.processes):
                errs.append(f"cohort {c.name}: suppresses unknown process {s!r}")
            for a, b in c.redirect.items():
                for x in (a, b):
                    if x not in k.actions:
                        errs.append(f"cohort {c.name}: redirect names unknown action {x!r}")
        for p in self.processes:
            if p.cohort not in names:
                errs.append(f"overlay process {p.name}: unknown cohort {p.cohort!r}")
        return errs


class _ArrivalSource(Source):
    """Creates a sized cohort's members uniformly over its arrival window."""

    def __init__(self, name: str, c: Cohort):
        super().__init__(name, self._run)
        self.c = c

    def _run(self, src: Any) -> None:
        c, days = self.c, src._e.run.days
        start, span = c.arrive
        if c.arrive_share is not None:
            span = days * c.arrive_share
        elif span is None:
            span = days - start
        if c.size is not None:
            n = int(c.size)
        elif c.share is not None:
            base = sum(1 for p in src._e.parts.values() if p.ns == 0 and p.kind.name == c.kind)
            n = max(1, round(base * c.share))
        else:
            n = int(src.rng.poisson(c.rate * span))
        for t in sorted(src.rng.uniform(start, start + span, n)):
            src.create(c.kind, at=float(t) * 86_400.0, cohort=c.name, **c.init)
