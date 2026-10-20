"""The pack API: tables, events, partition kinds (owners and shards), processes, actions,
sources and checks.

A pack module defines a `Config` dataclass and `define(p: Pack)`. `define` only declares;
behavior runs later in the engine, and reads the run's config as `ctx.cfg`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from neorisk_simkit.spec.types import COMMON, LType, i64, ts

NAME = re.compile(r"^[a-z][a-z0-9_]*$")
CONTINUATION, MESSAGE, TIMER = 0, 1, 2       # same-time precedence: lower runs first


class PackError(ValueError):
    pass


def _name(kind: str, name: str) -> str:
    if not NAME.match(name):
        raise PackError(f"{kind} name {name!r} must be lower_snake_case")
    return name


@dataclass(frozen=True)
class Latency:
    """A boundary's response time in seconds, uniform in [min, max]; min is δ and must be > 0."""
    min: float
    max: float | None = None

    @property
    def hi(self) -> float:
        return self.min if self.max is None else self.max


@dataclass
class Table:
    name: str
    cols: dict[str, LType]
    doc: str = ""
    key: str | None = None            # entity tables: the id column
    kind: str = "event"               # "event" | "entity"

    def columns(self) -> dict[str, LType]:
        """Every exported column, in order (common columns first for events)."""
        if self.kind == "event":
            return {**COMMON, **self.cols}
        return {self.key: i64(doc="Sequential id"), "created_at": ts(), **self.cols}


@dataclass
class Action:
    name: str
    fn: Callable[..., Any]
    kind: str
    process: str
    priority: int | None = None       # overrides the delivery's default priority
    id: int = -1                      # assigned by the plan


@dataclass
class Process:
    """Behavior that lives in one partition kind. `start` runs when a partition is created."""
    name: str
    kind: Kind
    start: str | None = None
    max_spawn_depth: int = 3
    doc: str = ""
    machine: Any = None               # a machine.Machine, when the process is a state machine
    cohort: str | None = None         # overlay processes run only for this cohort's members

    def action(self, fn: Callable | None = None, *, name: str | None = None,
               priority: int | None = None):
        def reg(f: Callable) -> Callable:
            n = _name("action", name or f.__name__)
            if n in self.kind.actions:
                raise PackError(f"{self.kind.name}: duplicate action {n!r}")
            self.kind.actions[n] = Action(n, f, self.kind.name, self.name, priority)
            return f
        return reg(fn) if fn is not None else reg


@dataclass
class Kind:
    """A partition kind: `owner` (a user, payment, campaign) or `shard` (a pool, a book)."""
    name: str
    role: str
    state: type
    latency: Latency
    doc: str = ""
    processes: dict[str, Process] = field(default_factory=dict)
    actions: dict[str, Action] = field(default_factory=dict)

    def process(self, name: str, *, start: str | None = None, max_spawn_depth: int = 3,
                doc: str = "") -> Process:
        _name("process", name)
        if name in self.processes:
            raise PackError(f"{self.name}: duplicate process {name!r}")
        p = Process(name, self, start, max_spawn_depth, doc)
        self.processes[name] = p
        return p

    def machine(self, name: str, *, initial: str, cohort: str | None = None):
        """A state-machine process (see `neorisk_simkit.machine`)."""
        from neorisk_simkit.machine import attach
        return attach(self, name, initial=initial, cohort=cohort)

    def action(self, fn: Callable | None = None, **kw):
        """An action in the kind's default process (named like the kind)."""
        if self.name not in self.processes:
            self.process(self.name)
        return self.processes[self.name].action(fn, **kw)


@dataclass
class Source:
    name: str
    fn: Callable[..., None]


@dataclass
class CheckSpec:
    name: str
    fn: Callable[..., Any]
    group: str = "law"                # structural | law | cross | stat
    required: bool = True
    doc: str = ""


class Pack:
    def __init__(self, name: str, config: type | None = None, doc: str = "",
                 schema_version: int = 1):
        """`schema_version` must go up on any column change (`datagen schema --diff`)."""
        self.name, self.config, self.doc = _name("pack", name), config, doc
        self.schema_version = schema_version
        self.entities: dict[str, Table] = {}
        self.events: dict[str, Table] = {}
        self.kinds: dict[str, Kind] = {}
        self.sources: list[Source] = []
        self.checks: list[CheckSpec] = []

    def _free(self, name: str) -> str:
        _name("table", name)
        if name in self.entities or name in self.events or name == "labels":
            raise PackError(f"duplicate table {name!r}")
        return name

    def entity(self, name: str, *, key: str, cols: dict[str, LType], doc: str = "") -> Table:
        t = Table(self._free(name), dict(cols), doc, key=key, kind="entity")
        self.entities[name] = t
        return t

    def event(self, name: str, *, cols: dict[str, LType], doc: str = "") -> Table:
        clash = set(cols) & set(COMMON)
        if clash:
            raise PackError(f"event {name!r} redeclares common columns {sorted(clash)}")
        t = Table(self._free(name), dict(cols), doc)
        self.events[name] = t
        return t

    def _kind(self, name: str, role: str, state: type, latency: Latency, doc: str) -> Kind:
        _name("kind", name)
        if name in self.kinds:
            raise PackError(f"duplicate partition kind {name!r}")
        k = Kind(name, role, state, latency, doc)
        self.kinds[name] = k
        return k

    def owner(self, name: str, *, state: type, latency: Latency | None = None,
              doc: str = "") -> Kind:
        """`latency` is the delay of messages delivered to this owner (default 50 ms)."""
        return self._kind(name, "owner", state, latency or Latency(0.05), doc)

    def shard(self, name: str, *, state: type, latency: Latency, doc: str = "") -> Kind:
        """`latency` is the response time of requests to this shard."""
        return self._kind(name, "shard", state, latency, doc)

    def source(self, fn: Callable | None = None, *, name: str | None = None):
        """Register `fn(src)`, run once before the loop to seed partitions and tables."""
        def reg(f: Callable) -> Callable:
            self.sources.append(Source(_name("source", name or f.__name__), f))
            return f
        return reg(fn) if fn is not None else reg

    def check(self, name: str, fn: Callable, *, group: str = "law", required: bool = True,
              doc: str = "") -> None:
        if any(c.name == name for c in self.checks):
            raise PackError(f"duplicate check {name!r}")
        self.checks.append(CheckSpec(name, fn, group, required, doc))
