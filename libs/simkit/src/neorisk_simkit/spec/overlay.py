"""Overlays (spec §08): add a configurable group of actors to a base pack without editing it.
An overlay sees the base only through `p.expose(...)`, `p.expose_param(...)` and
`p.expose_owner(...)`; it adds cohorts, machines on them and labels, never events, tables,
processes or boundaries (D74, D95)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from neorisk_simkit.spec.dist import BURST, Dist
from neorisk_simkit.spec.pack import Pack, PackError
from neorisk_simkit.spec.types import boolean, cat, i16, ref, ts


@dataclass(frozen=True)
class CohortDef:
    name: str
    table: str                 # the base table its members are rows of
    partition: str             # its own owner partition (= name)
    base_partition: str
    size: int
    suppress: tuple[str, ...]
    attrs: tuple[tuple[str, Any], ...]
    refs: tuple[str, ...]
    labels: str | None
    overlay: str


@dataclass
class Cohort:
    name: str
    table: str
    base_partition: str
    size: int
    suppress: tuple[str, ...]
    attrs: dict
    refs: dict
    overlay: str
    labels: str | None = None
    label_delay: Dist | None = None
    machines: list = field(default_factory=list)

    @property
    def partition(self) -> str:
        return self.name

    def spawned(self, machine: str) -> Spawned:
        """Members of `machine` instances spawned by other machines of this cohort."""
        return Spawned(self, machine)

    def define(self) -> CohortDef:
        return CohortDef(self.name, self.table, self.name, self.base_partition, self.size,
                         self.suppress, tuple(self.attrs.items()), tuple(self.refs),
                         self.labels, self.overlay)


@dataclass(frozen=True)
class Spawned:
    cohort: Cohort
    machine: str


class _Base:
    """`o.base.<name>`: what the base pack exposed with `p.expose(...)`."""

    def __init__(self, exposed: dict):
        self._exposed = exposed

    def __getattr__(self, name: str):
        try:
            return self._exposed[name]
        except KeyError:
            raise AttributeError(f"base pack exposes no {name!r}") from None


class Overlay:
    """The surface `apply(o, **params)` gets. No `event`, `table`, `process`, `request`,
    `message` or `shard`: overlays add no schema (D74, D95)."""

    def __init__(self, pack: Pack, name: str):
        self._p, self.name = pack, name
        self.base = _Base(pack.exposed)

    def param(self, path: str):
        if path not in self._p.exposed_params:
            raise PackError(f"overlay {self.name}: base pack exposes no parameter {path!r}")
        return self._p.exposed_params[path]

    def cohort(self, name: str, *, table: str, size: int | None = None,
               share: float | None = None, rate: float | None = None,
               arrivals: Dist | None = None, execution_owner: str | None = None,
               suppress=(), attrs: dict | None = None, refs: dict | None = None) -> Cohort:
        """A cohort: `size` members' campaigns (or `share` of the base population, or `rate`
        per day of a `dist.burst` window), each its own owner of partition `name` acting for
        the exposed owner partition of `table` (D74). `attrs` are member row values, `refs`
        population refs recipes of the campaign owners (their rows append to the base tables,
        D94)."""
        p = self._p
        base = next((q for q in p.partitions.values()
                     if q["kind"] == "owner" and q["table"] == table), None)
        if base is None or base["name"] not in p.exposed_owners:
            raise PackError(f"cohort {name}: table {table!r} has no exposed owner partition")
        if sum(x is not None for x in (size, share, rate)) != 1:
            raise PackError(f"cohort {name}: give exactly one of size=, share=, rate=")
        if size is not None:
            n = int(size)
        elif share is not None:
            n = round(share * p.populations[table]["n"])
        else:
            if arrivals is None or arrivals.kind != BURST:
                raise PackError(f"cohort {name}: rate= needs arrivals=dist.burst(...)")
            n = round(rate * arrivals.params[1])
        if n < 0:
            raise PackError(f"cohort {name}: size must be >= 0")
        known = {q["name"] for q in p.processes.values() if q["partition"] == base["name"]}
        known |= {m.name for m in p.machines.values() if m.partition == base["name"]}
        for s in suppress:
            if s not in known:
                raise PackError(f"cohort {name}: suppress names unknown process {s!r} of "
                                f"partition {base['name']!r}")
        unknown = sorted(set(attrs or {}) - set(p.tables[table]["cols"]))
        if unknown:
            raise PackError(f"cohort {name}: attrs names unknown columns {unknown} of {table!r}")
        t = p.table(name, key=execution_owner or f"{name}_id", mutable=True,
                    cols={"members": i16()},
                    doc=f"Execution owner of overlay {self.name} cohort {name}")
        p.owner(name, table=t, max_live=max(1, n), acts_for=base["name"])
        p.population(t, n=n, initial=0.0 if arrivals is not None else 1.0,
                     arrivals=arrivals, refs=refs)
        c = Cohort(name, table, base["name"], n, tuple(suppress), dict(attrs or {}),
                   dict(refs or {}), self.name)
        p.cohorts[name] = c
        return c

    def machine(self, name: str, *, members, initial: str, fields=None, init=None,
                member=None, max_instances: int = 1, config=None, reads=None,
                max_spawn_depth=None):
        """A machine on a cohort's campaign owner. `members=cohort`: one root instance per
        campaign, started when the campaign arrives, whose actor is a new member row; with
        `members=cohort.spawned(name)` its instances are spawned by other machines, each with
        its own member row. `member` gives member row values (over the cohort's `attrs`;
        `std.parent()` is the spawning instance's actor), `init` root instance fields."""
        cohort = members.cohort if isinstance(members, Spawned) else members
        if not isinstance(cohort, Cohort):
            raise PackError(f"machine {name}: members= must be a cohort or cohort.spawned(...)")
        if isinstance(members, Spawned) and members.machine != name:
            raise PackError(f"machine {name}: members=cohort.spawned({members.machine!r}) "
                            f"names another machine")
        root = isinstance(members, Cohort)
        if init and not root:
            raise PackError(f"machine {name}: init= is for root machines (spawned instances "
                            "take fields from std.spawn(fields=...))")
        extra = {"labels": cohort.labels, "label_delay": cohort.label_delay} \
            if cohort.labels is not None else {}
        m = self._p.machine(
            name, owner=cohort.partition, initial=initial,
            start=self._p.on_created(cohort.name) if root else None, config=config,
            max_instances=max_instances, fields=fields, reads=reads,
            refs={r: r for r in cohort.refs}, max_spawn_depth=max_spawn_depth,
            member_table=cohort.table, root_member=root,
            member_values=tuple({**cohort.attrs, **(member or {})}.items()),
            root_init=tuple((init or {}).items()), overlay=self.name, **extra)
        cohort.machines.append(m)
        return m

    def label(self, cohort: Cohort, *, roles, outcomes, available_after: Dist) -> None:
        """Hidden labels of the cohort's members (D76): `labels_<cohort>` with `target_id`,
        `campaign_id`, `role`, `outcome`, `final_label`, `label_available_at`; machines write
        rows with `std.label(role, outcome)`."""
        if not isinstance(available_after, Dist):
            raise PackError(f"label {cohort.name}: available_after must be a Dist")
        name = f"labels_{cohort.name}"
        self._p.labels(name, owner=cohort.partition, cols={
            "target_id": ref(cohort.table), "campaign_id": ref(cohort.name),
            "role": cat(*roles), "outcome": cat(*outcomes), "final_label": boolean(),
            "label_available_at": ts()})
        cohort.labels, cohort.label_delay = name, available_after
        for m in cohort.machines:
            m.extra.update(labels=name, label_delay=available_after)
