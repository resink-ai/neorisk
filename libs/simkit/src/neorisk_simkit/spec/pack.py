"""The pack authoring API: `define(p: Pack, cfg)` declares tables, partitions, boundaries and
processes. `Pack` records declarations in order and checks what it can locally; `spec.plan`
normalizes them into a `Plan` (codes, ref resolution, creatable namespaces)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from neorisk_simkit.engine.abi import KernelSpec
from neorisk_simkit.spec.dist import Dist
from neorisk_simkit.spec.law import LawSpec
from neorisk_simkit.spec.sources import Source
from neorisk_simkit.spec.types import COMMON_COLUMNS, LType

MAX_PARTITION_TYPES = 31                     # ptype_code is 5 bits (D12)
_STATE_RE = re.compile(r"^(i8|i16|i32|i64|u8|u32|f64|ref)(?:\[(\w+)\])?$")
_COMMON = frozenset(n for n, _ in COMMON_COLUMNS)


class PackError(Exception):
    """A pack declaration is invalid."""


@dataclass(frozen=True)
class Trigger:
    """When a process starts: `kind == "created"` = when a row of `table` is created."""
    kind: str
    table: str


def _cols(what: str, cols: dict[str, LType]) -> dict[str, LType]:
    for name, t in cols.items():
        if not isinstance(t, LType):
            raise PackError(f"{what}.{name}: expected a column type, got {type(t).__name__}")
    return dict(cols)


class Pack:
    def __init__(self, name: str, schema_version: int):
        self.name = name
        self.schema_version = schema_version
        self.tables: dict[str, dict[str, Any]] = {}
        self.events: dict[str, dict[str, Any]] = {}
        self.ids_names: list[str] = []
        self.partitions: dict[str, dict[str, Any]] = {}
        self.boundaries: dict[str, dict[str, Any]] = {}
        self.populations: dict[str, dict[str, Any]] = {}
        self.processes: dict[str, dict[str, Any]] = {}
        self.change_groups: dict[str, dict[str, Any]] = {}
        self.checks: dict[str, tuple[LawSpec, bool]] = {}
        self.accumulators: dict[str, dict[str, Any]] = {}
        self.exposed_owners: list[str] = []
        self.machines: dict[str, Any] = {}           # name -> machine.spec.Machine builder

    # ------------------------------------------------------------------ helpers
    def _table(self, name: str) -> dict[str, Any]:
        if name not in self.tables:
            raise PackError(f"unknown table {name!r}")
        return self.tables[name]

    def _partition(self, name: str, kind: str | None = None) -> dict[str, Any]:
        if name not in self.partitions:
            raise PackError(f"unknown partition {name!r}")
        part = self.partitions[name]
        if kind is not None and part["kind"] != kind:
            raise PackError(f"partition {name!r} is not a{'n' if kind == 'owner' else ''} {kind}")
        return part

    def _new_partition(self, name: str) -> None:
        if name in self.partitions:
            raise PackError(f"duplicate partition {name!r}")
        if len(self.partitions) >= MAX_PARTITION_TYPES:
            raise PackError(f"at most {MAX_PARTITION_TYPES} partition types")

    def _new_record_type(self, what: str, name: str) -> None:
        if name in self.events or name in self.change_groups:
            raise PackError(f"duplicate {what} {name!r} (events, postings and change groups "
                            f"share names)")

    # ------------------------------------------------------------------ tables and ids
    def table(self, name: str, *, key: str, cols: dict[str, LType], mutable: bool = False,
              doc: str = "", child_of: str | None = None, source: Source | None = None) -> str:
        if name in self.tables:
            raise PackError(f"duplicate table {name!r}")
        if name in self.ids_names:
            raise PackError(f"table {name!r} clashes with an ids namespace")
        cols = _cols(f"table {name}", cols)
        if key in cols:
            raise PackError(f"table {name}: key {key!r} must not also be a column")
        if child_of is not None:
            self._table(child_of)
        if source is not None:
            if not isinstance(source, Source):
                raise PackError(f"table {name}: source must be a Source")
            extra = sorted(set(source.cols) - set(cols))
            if extra:
                raise PackError(f"table {name}: source generates unknown columns {extra}")
        self.tables[name] = {"name": name, "key": key, "cols": cols, "mutable": mutable,
                             "doc": doc, "child_of": child_of, "source": source}
        return name

    def ids(self, *names: str) -> None:
        for n in names:
            if n in self.ids_names or n in self.tables:
                raise PackError(f"duplicate ids namespace {n!r}")
            self.ids_names.append(n)

    # ------------------------------------------------------------------ partitions
    def owner(self, name: str, *, table: str, max_live: int, children=(),
              retire_when_idle: bool = True, execution_owner: str | None = None,
              acts_for: str | None = None) -> str:
        """`acts_for` (D74): this owner executes on behalf of the exposed owner partition
        `acts_for` - its processes may emit that partition's records, send its boundaries and
        create member rows of its table (`out.add_member_<table>`)."""
        self._new_partition(name)
        t = self._table(table)
        if acts_for is not None:
            self._partition(acts_for, "owner")
            if acts_for not in self.exposed_owners:
                raise PackError(f"owner {name}: acts_for {acts_for!r} needs "
                                f"p.expose_owner({acts_for!r}) in the base pack")
        if not t["mutable"]:
            raise PackError(f"owner {name}: table {table!r} must be mutable")
        if max_live < 1:
            raise PackError(f"owner {name}: max_live must be >= 1")
        for c in children:
            self._table(c)
        self.partitions[name] = {
            "kind": "owner", "name": name, "table": table, "n": None, "max_live": int(max_live),
            "items": None, "key": t["key"], "state": {}, "init": None,
            "retire_when_idle": retire_when_idle, "doc": "", "acts_for": acts_for}
        return name

    def expose_owner(self, name: str) -> None:
        """Expose owner partition `name` as an execution-owner extension point (D74): an owner
        declared with `acts_for=name` may act for it."""
        self._partition(name, "owner")
        if name not in self.exposed_owners:
            self.exposed_owners.append(name)

    def shard(self, name: str, *, key: str, n: int, items: str | None, state: dict[str, str],
              init=None, doc: str = "") -> str:
        self._new_partition(name)
        if n < 1:
            raise PackError(f"shard {name}: n must be >= 1")
        if items is not None:
            t = self._table(items)
            if key not in t["cols"]:
                raise PackError(f"shard {name}: key {key!r} is not a column of {items!r}")
        for field, decl in state.items():
            m = _STATE_RE.match(decl)
            if m is None:
                raise PackError(f"shard {name}: unknown state type {decl!r} for {field!r}")
            if m.group(2) is not None:
                if items is None:
                    raise PackError(f"shard {name}: per-item state needs items=")
                if m.group(2) != items:
                    raise PackError(f"shard {name}: state {field!r} is per {m.group(2)!r}, "
                                    f"but the shard's items are {items!r}")
        if init is not None and hasattr(init, "bind"):    # a recipe learns its items table
            try:
                init = init.bind(items=items)
            except ValueError as e:
                raise PackError(f"shard {name}: {e}") from None
        self.partitions[name] = {
            "kind": "shard", "name": name, "table": None, "n": int(n), "max_live": int(n),
            "items": items, "key": key, "state": dict(state), "init": init,
            "retire_when_idle": False, "doc": doc, "acts_for": None}
        return name

    # ------------------------------------------------------------------ boundaries
    def _boundary(self, kind: str, name: str, frm: str, to: str, payload: dict[str, LType],
                  latency: Dist, responses=(), response_payload=None) -> str:
        if name in self.boundaries:
            raise PackError(f"duplicate boundary {name!r}")
        self._partition(frm)
        self._partition(to)
        if not isinstance(latency, Dist):
            raise PackError(f"boundary {name}: latency must be a Dist")
        responses = tuple(responses)
        if len(set(responses)) != len(responses):
            raise PackError(f"boundary {name}: duplicate response names")
        self.boundaries[name] = {
            "kind": kind, "name": name, "frm": frm, "to": to,
            "payload": _cols(f"boundary {name}", payload),
            "response_payload": _cols(f"boundary {name}", response_payload or {}),
            "responses": responses, "latency": latency}
        return name

    def request(self, name: str, *, frm: str, to: str, payload: dict[str, LType], responses,
                latency: Dist, response_payload: dict[str, LType] | None = None) -> str:
        if not responses:
            raise PackError(f"request {name}: needs at least one response")
        return self._boundary("request", name, frm, to, payload, latency, responses,
                              response_payload)

    def message(self, name: str, *, frm: str, to: str, payload: dict[str, LType],
                latency: Dist) -> str:
        return self._boundary("message", name, frm, to, payload, latency)

    # ------------------------------------------------------------------ records
    def event(self, name: str, *, cols: dict[str, LType], owner: str | None = None,
              shard: str | None = None, doc: str = "") -> str:
        return self._record("event", "events", name, cols, owner, shard, doc)

    def postings(self, name: str, *, cols: dict[str, LType], owner: str | None = None,
                 shard: str | None = None, doc: str = "") -> str:
        """An append-only posting table (D45): written like an event (`out.emit_<name>`), kept
        apart from events in `postings/`, counted in `posting_counts`, never replayed."""
        return self._record("postings", "postings", name, cols, owner, shard, doc)

    def labels(self, name: str, *, cols: dict[str, LType], owner: str | None = None,
               shard: str | None = None, doc: str = "") -> str:
        """Hidden label records (D76): written like an event (`out.emit_<name>`), kept apart in
        `labels/`, counted in `label_counts`, never exported as events, indexed or replayed,
        and never read by a law (F-24)."""
        return self._record("labels", "labels", name, cols, owner, shard, doc)

    def _record(self, what: str, group: str, name: str, cols: dict[str, LType],
                owner: str | None, shard: str | None, doc: str) -> str:
        self._new_record_type(what, name)
        if (owner is None) == (shard is None):
            raise PackError(f"{what} {name}: give exactly one of owner= or shard=")
        part = self._partition(owner, "owner") if owner is not None else self._partition(
            shard, "shard")
        cols = _cols(f"{what} {name}", cols)
        clash = sorted(set(cols) & _COMMON)
        if clash:
            raise PackError(f"{what} {name}: columns {clash} clash with the common columns")
        self.events[name] = {"name": name, "partition": part["name"], "kind": part["kind"],
                             "cols": cols, "doc": doc, "group": group}
        return name

    def change_group(self, name: str, *, table: str, cols) -> None:
        self._new_record_type("change group", name)
        t = self._table(table)
        if not t["mutable"]:
            raise PackError(f"change group {name}: table {table!r} must be mutable")
        cols = tuple(cols)
        missing = [c for c in cols if c not in t["cols"]]
        if missing:
            raise PackError(f"change group {name}: unknown columns {missing} of {table!r}")
        self.change_groups[name] = {"name": name, "table": table, "cols": cols}

    # ------------------------------------------------------------------ populations, processes
    def population(self, table: str, *, n: int, initial: float, arrivals: Dist | None = None,
                   attrs: dict[str, Dist] | None = None, refs: dict[str, Any] | None = None
                   ) -> None:
        t = self._table(table)
        if table in self.populations:
            raise PackError(f"duplicate population of {table!r}")
        if n < 0:
            raise PackError(f"population {table}: n must be >= 0")
        if not 0.0 <= initial <= 1.0:
            raise PackError(f"population {table}: initial must be in [0, 1]")
        attrs = dict(attrs or {})
        unknown = sorted(set(attrs) - set(t["cols"]))
        if unknown:
            raise PackError(f"population {table}: unknown attrs {unknown}")
        self.populations[table] = {"table": table, "n": int(n), "initial": float(initial),
                                   "arrivals": arrivals, "attrs": attrs,
                                   "refs": dict(refs or {})}

    def on_created(self, table: str) -> Trigger:
        self._table(table)
        return Trigger("created", table)

    def process(self, name: str, *, kernel, owner: str | None = None, shard: str | None = None,
                config=None, start: Trigger | None = None, requests=None, messages=None,
                on_request=None, on_response=None, on_message=None, reads=None, refs=None,
                commands=(), every=None, jitter: Dist | None = None,
                max_spawn_depth: int | None = None) -> None:
        if name in self.processes or name in self.machines:
            raise PackError(f"duplicate process {name!r}")
        if (owner is None) == (shard is None):
            raise PackError(f"process {name}: give exactly one of owner= or shard=")
        part = self._partition(owner, "owner") if owner is not None else self._partition(
            shard, "shard")
        spec = getattr(kernel, "__kernel__", None)
        if not isinstance(spec, KernelSpec):
            raise PackError(f"process {name}: kernel must be a @kernel function")
        if start is not None and not isinstance(start, Trigger):
            raise PackError(f"process {name}: start= must come from p.on_created(...)")
        requests, messages = dict(requests or {}), dict(messages or {})
        for local, b in (*requests.items(), *messages.items()):
            if b not in self.boundaries:
                raise PackError(f"process {name}: unknown boundary {b!r} for {local!r}")
        for b in (*(on_request or {}), *(on_message or {}), *(k for k, _ in on_response or {})):
            if b not in self.boundaries:
                raise PackError(f"process {name}: handles unknown boundary {b!r}")
        for (b, r) in on_response or {}:
            if r not in self.boundaries[b]["responses"]:
                raise PackError(f"process {name}: boundary {b!r} has no response {r!r}")
        reads = dict(reads or {})
        for t in reads.values():
            self._table(t)
        self.processes[name] = {
            "name": name, "partition": part["name"], "kernel": spec, "config": config,
            "start": start, "requests": requests, "messages": messages,
            "on_request": dict(on_request or {}), "on_response": dict(on_response or {}),
            "on_message": dict(on_message or {}), "reads": reads, "refs": dict(refs or {}),
            "commands": tuple(commands) or spec.commands, "every": every, "jitter": jitter,
            "max_spawn_depth": max_spawn_depth}

    def check(self, id: str, law: LawSpec, required: bool = False) -> None:
        if id in self.checks:
            raise PackError(f"duplicate check {id!r}")
        if not isinstance(law, LawSpec):
            raise PackError(f"check {id}: law must come from std.law")
        self.checks[id] = (law, bool(required))

    def accumulator(self, name: str, ltype: LType) -> str:
        """An additive accumulator (D46): kernels add to it with `out.add_<name>(value)` and
        never read it; the manifest holds its total over exported steps."""
        if name in self.accumulators:
            raise PackError(f"duplicate accumulator {name!r}")
        if not isinstance(ltype, LType) or ltype.kind not in ("i64", "amount") \
                or ltype.nullable:
            raise PackError(f"accumulator {name}: type must be i64 or amount")
        if not name.isidentifier():
            raise PackError(f"accumulator {name!r}: name must be an identifier "
                            f"(kernels call out.add_<name>)")
        self.accumulators[name] = {"name": name, "ltype": ltype}
        return name

    # ------------------------------------------------------------------ machines
    def machine(self, name: str, *, owner: str, initial: str, start: Trigger | None = None,
                config=None, max_instances: int = 1, fields=None, reads=None, refs=None,
                max_spawn_depth: int | None = None, **extra):
        """Declare a state machine on an owner partition (spec §04); returns its builder
        (`.state(...)`, `.final(...)`). `build_plan` validates and compiles it."""
        from neorisk_simkit.machine.spec import Machine
        if name in self.machines or name in self.processes:
            raise PackError(f"duplicate machine {name!r}")
        part = self.partitions.get(owner)
        if part is None or part["kind"] != "owner":
            raise PackError(f"machine {name}: machines live on owner partitions (got {owner!r})")
        if start is not None and not isinstance(start, Trigger):
            raise PackError(f"machine {name}: start= must come from p.on_created(...)")
        for t in (reads or {}).values():
            self._table(t)
        m = Machine(name, owner, initial=initial, start=start, config=config,
                    max_instances=max_instances, fields=fields, reads=reads, refs=refs,
                    max_spawn_depth=max_spawn_depth, **extra)
        self.machines[name] = m
        return m

    # ------------------------------------------------------------------ later tasks, milestones
    def expose(self, *args, **kwargs):
        raise PackError("expose arrives in M3")

    def expose_param(self, *args, **kwargs):
        raise PackError("expose_param arrives in M3")

    def feature(self, *args, **kwargs):
        raise PackError("feature arrives in M4 (D-deferred)")
