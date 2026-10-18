"""The normalized plan: every declaration of a pack with codes assigned and refs resolved."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from neorisk_simkit.engine.abi import KernelSpec
from neorisk_simkit.spec import dist as _dist
from neorisk_simkit.spec.dist import Dist
from neorisk_simkit.spec.law import LawSpec
from neorisk_simkit.spec.pack import Pack, PackError, Trigger
from neorisk_simkit.spec.sources import Source
from neorisk_simkit.spec.types import COMMON_COLUMNS, LType


@dataclass(frozen=True)
class Column:
    name: str
    ltype: LType


@dataclass(frozen=True)
class TableDef:
    name: str
    code: int
    key: str
    cols: tuple[Column, ...]
    mutable: bool
    doc: str
    child_of: str | None
    source: Source | None
    creatable: bool


@dataclass(frozen=True)
class EventDef:
    name: str
    code: int
    partition: str
    kind: str                         # "owner" | "shard"
    doc: str
    cols: tuple[Column, ...]          # the 8 common columns first
    group: str = "events"             # "events" | "postings" (D45)


@dataclass(frozen=True)
class PartitionDef:
    name: str
    kind: str                         # "owner" | "shard"
    ptype_code: int                   # 1 + declaration index (D12)
    table: str | None                 # owner: its state table; shard: None
    n: int | None                     # shard: number of shards; owner: None
    max_live: int                     # owner: live-slot cap; shard: n
    items: str | None                 # shard: items table (D25), or None
    key: str                          # owner: table key; shard: items column grouping items
    state: Mapping[str, str]          # shard: field -> "T" or "T[<items>]"; owner: empty
    init: Any                         # shard state init (dict of Dist / recipe), or None
    retire_when_idle: bool


@dataclass(frozen=True)
class BoundaryDef:
    name: str
    code: int
    kind: str                         # "request" | "message"
    frm: str
    to: str
    payload: tuple[Column, ...]
    response_payload: tuple[Column, ...]
    responses: tuple[str, ...]
    latency: Dist
    min_latency_us: int
    o2o: bool = False                 # an owner-to-owner message (D73)


@dataclass(frozen=True)
class ProcessDef:
    name: str
    partition: str
    action_id: int
    kernel: KernelSpec
    config: Any
    start: Trigger | None
    requests: Mapping[str, str]                     # local name -> boundary
    messages: Mapping[str, str]                     # local name -> boundary
    on_request: Mapping[str, int]                   # boundary -> command id
    on_response: Mapping[tuple[str, str], int]      # (boundary, response) -> command id
    on_message: Mapping[str, int]                   # boundary -> command id
    reads: Mapping[str, str]                        # local name -> table
    refs: Mapping[str, Any]                         # local name -> population refs name
    commands: tuple[int, ...]
    every_us: int | None
    jitter: Dist | None
    max_spawn_depth: int | None = None              # None: budget.max_spawn_depth (D72)


@dataclass(frozen=True)
class PopulationDef:
    table: str
    n: int
    initial: float
    arrivals: Dist | None
    attrs: Mapping[str, Dist]
    refs: Mapping[str, Any]


@dataclass(frozen=True)
class ChangeGroupDef:
    name: str
    code: int
    table: str
    cols: tuple[Column, ...]


@dataclass(frozen=True)
class CheckDef:
    id: str
    law: LawSpec
    required: bool


@dataclass(frozen=True)
class AccumulatorDef:
    name: str
    code: int
    ltype: LType                      # kind "i64" or "amount" (D46)


def _find(items, name: str, what: str):
    for it in items:
        if it.name == name:
            return it
    raise KeyError(f"unknown {what} {name!r}")


@dataclass(frozen=True)
class Plan:
    pack: str
    schema_version: int
    revision: str
    tables: tuple[TableDef, ...]
    events: tuple[EventDef, ...]
    namespaces: tuple[str, ...]
    partitions: tuple[PartitionDef, ...]
    boundaries: tuple[BoundaryDef, ...]
    processes: tuple[ProcessDef, ...]
    populations: tuple[PopulationDef, ...]
    change_groups: tuple[ChangeGroupDef, ...]
    checks: tuple[CheckDef, ...]
    cfg: Any
    accumulators: tuple[AccumulatorDef, ...] = ()

    def table(self, name: str) -> TableDef:
        return _find(self.tables, name, "table")

    def event(self, name: str) -> EventDef:
        return _find(self.events, name, "event")

    def partition(self, name: str) -> PartitionDef:
        return _find(self.partitions, name, "partition")

    def boundary(self, name: str) -> BoundaryDef:
        return _find(self.boundaries, name, "boundary")

    def process(self, name: str) -> ProcessDef:
        return _find(self.processes, name, "process")

    def change_group(self, name: str) -> ChangeGroupDef:
        return _find(self.change_groups, name, "change group")

    def ns_code(self, name: str) -> int:
        try:
            return self.namespaces.index(name)
        except ValueError:
            raise KeyError(f"unknown namespace {name!r}") from None


def pack_revision(specs_dir: Path) -> str:
    """D22: first 7 hex of sha256 over specs/**/*.py and specs/expectations.yaml."""
    files = [p for p in specs_dir.rglob("*.py") if "__pycache__" not in p.parts]
    exp = specs_dir / "expectations.yaml"
    if exp.is_file():
        files.append(exp)
    h = hashlib.sha256()
    for p in sorted(files, key=lambda p: p.relative_to(specs_dir).as_posix()):
        h.update(p.relative_to(specs_dir).as_posix().encode() + b"\0")
        h.update(p.read_bytes() + b"\0")
    return h.hexdigest()[:7]


def _frozen(d: dict) -> Mapping:
    return MappingProxyType(dict(d))


def build_plan(pack_module, cfg, specs_dir: Path) -> Plan:
    """Run the pack's `define(p, cfg)` and normalize the declarations into a `Plan`."""
    from neorisk_simkit.spec.project import parse_duration  # project imports this module

    p = Pack(pack_module.PACK, pack_module.SCHEMA_VERSION)
    pack_module.define(p, cfg)

    ref_targets = set(p.tables) | set(p.ids_names)

    def resolve(where: str, cols: dict[str, LType]) -> tuple[Column, ...]:
        for c, t in cols.items():
            if t.kind == "ref" and t.target not in ref_targets:
                raise PackError(f"unknown ref target {t.target!r} in {where}.{c}")
        return tuple(Column(c, t) for c, t in cols.items())

    owner_tables = {d["table"] for d in p.partitions.values() if d["kind"] == "owner"}
    for table in p.populations:
        if table not in owner_tables:
            raise PackError(f"population {table}: no owner partition uses table {table!r}")

    tables = tuple(
        TableDef(name=d["name"], code=i, key=d["key"], cols=resolve(f"table {d['name']}",
                 d["cols"]), mutable=d["mutable"], doc=d["doc"], child_of=d["child_of"],
                 source=d["source"],
                 creatable=d["child_of"] is not None or (
                     d["name"] in owner_tables and d["name"] not in p.populations))
        for i, d in enumerate(p.tables.values()))
    namespaces = tuple(t.name for t in tables if t.creatable) + tuple(p.ids_names)

    common = tuple(Column(n, t) for n, t in COMMON_COLUMNS)
    events = tuple(
        EventDef(name=d["name"], code=i, partition=d["partition"], kind=d["kind"], doc=d["doc"],
                 cols=common + resolve(f"event {d['name']}", d["cols"]), group=d["group"])
        for i, d in enumerate(p.events.values()))

    partitions = tuple(
        PartitionDef(name=d["name"], kind=d["kind"], ptype_code=1 + i, table=d["table"],
                     n=d["n"], max_live=d["max_live"], items=d["items"], key=d["key"],
                     state=_frozen(d["state"]), init=d["init"],
                     retire_when_idle=d["retire_when_idle"])
        for i, d in enumerate(p.partitions.values()))

    kind_of = {pd.name: pd.kind for pd in partitions}
    boundaries = tuple(
        BoundaryDef(name=d["name"], code=i, kind=d["kind"], frm=d["frm"], to=d["to"],
                    payload=resolve(f"boundary {d['name']}", d["payload"]),
                    response_payload=resolve(f"boundary {d['name']}", d["response_payload"]),
                    responses=d["responses"], latency=d["latency"],
                    min_latency_us=_dist.min_us(d["latency"]),
                    o2o=(d["kind"] == "message" and kind_of.get(d["frm"]) == "owner"
                         and kind_of.get(d["to"]) == "owner"))
        for i, d in enumerate(p.boundaries.values()))

    def every_us(proc: str, every) -> int | None:
        if every is None:
            return None
        us = parse_duration(every) if isinstance(every, str) else int(every)
        if us <= 0:
            raise PackError(f"process {proc}: every= must be > 0")
        return us

    processes = tuple(
        ProcessDef(name=d["name"], partition=d["partition"], action_id=i, kernel=d["kernel"],
                   config=d["config"], start=d["start"], requests=_frozen(d["requests"]),
                   messages=_frozen(d["messages"]), on_request=_frozen(d["on_request"]),
                   on_response=_frozen(d["on_response"]), on_message=_frozen(d["on_message"]),
                   reads=_frozen(d["reads"]), refs=_frozen(d["refs"]), commands=d["commands"],
                   every_us=every_us(d["name"], d["every"]), jitter=d["jitter"],
                   max_spawn_depth=d["max_spawn_depth"])
        for i, d in enumerate(p.processes.values()))

    populations = tuple(
        PopulationDef(table=d["table"], n=d["n"], initial=d["initial"], arrivals=d["arrivals"],
                      attrs=_frozen(d["attrs"]), refs=_frozen(d["refs"]))
        for d in p.populations.values())

    def group_cols(table: str, names: tuple[str, ...]) -> tuple[Column, ...]:
        by_name = {c.name: c for c in _find(tables, table, "table").cols}
        return tuple(by_name[n] for n in names)

    change_groups = tuple(
        ChangeGroupDef(name=d["name"], code=i, table=d["table"],
                       cols=group_cols(d["table"], d["cols"]))
        for i, d in enumerate(p.change_groups.values()))

    checks = tuple(CheckDef(id=k, law=law, required=req) for k, (law, req) in p.checks.items())

    accumulators = tuple(AccumulatorDef(name=d["name"], code=i, ltype=d["ltype"])
                         for i, d in enumerate(p.accumulators.values()))

    return Plan(pack=p.name, schema_version=p.schema_version,
                revision=pack_revision(Path(specs_dir)), tables=tables, events=events,
                namespaces=namespaces, partitions=partitions, boundaries=boundaries,
                processes=processes, populations=populations, change_groups=change_groups,
                checks=checks, cfg=cfg, accumulators=accumulators)
