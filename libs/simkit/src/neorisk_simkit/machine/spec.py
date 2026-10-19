"""Machine declarations (spec §04): the builder `p.machine(...)` returns, the normalized
`MachineDef`, and the closed-semantics validation `build_machines` runs at plan build."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from neorisk_simkit.engine.abi import _LOCAL_RE, ActionSpec
from neorisk_simkit.machine import helpers as h
from neorisk_simkit.machine.layout import IMPLICIT, MAX_CHILDREN, READABLE_IMPLICIT, REPEAT_CAP
from neorisk_simkit.spec.dist import CATEGORICAL, GEOMETRIC, UNIFORM_INT, Dist
from neorisk_simkit.spec.pack import PackError, Trigger

MAX_MACHINES, MAX_STATES, MAX_INSTANCES = 16, 32, 64
LATE = ("ignore", "count")
IMPLICIT_FIELDS = tuple(f for f, _ in IMPLICIT)              # D63 (single source: layout)


@dataclass(frozen=True)
class Outcome:
    target: str
    p: Any                        # float | h.PBy | None (the unpicked mass, D71)
    delay: Dist | None
    chain: h.Chain | None


@dataclass(frozen=True)
class StateDef:
    name: str
    code: int                     # 1 + declaration index
    branch: tuple[Outcome, ...] = ()
    timers: tuple[tuple[str, Dist], ...] = ()
    repeat: tuple[Dist, float, h.Chain | None] | None = None
    max_repeats: Any = None       # int | Dist | h.Field | None
    until: h.Cond | None = None
    then: str | None = None
    join: tuple[str, str] | None = None             # (target, message)
    late: str = "ignore"
    request: tuple[str, h.Request] | None = None    # (target, request)
    on_reject: str | None = None
    on_timeout: str | None = None
    timeout_us: int | None = None
    spawn: tuple[tuple[str, float, Dist | None, Any], ...] = ()  # (child, p, delay, n)


@dataclass(frozen=True)
class MachineDef:
    name: str
    partition: str
    index: int                    # tag field m (position among the partition's machines)
    start: Trigger | None
    initial: str
    states: tuple[StateDef, ...]
    finals: tuple[str, ...]
    config: Any
    max_instances: int
    fields: Mapping[str, str]
    reads: Mapping[str, str]
    refs: Mapping[str, Any]
    max_spawn_depth: int | None
    member_table: str | None = None                 # cohort machines (Task 10)
    root_member: bool = False
    member_values: tuple[tuple[str, Any], ...] = ()
    root_init: tuple[tuple[str, Any], ...] = ()     # root instance fields set at START
    labels: str | None = None
    label_delay: Dist | None = None
    overlay: str | None = None

    def state(self, name: str) -> StateDef:
        return next(s for s in self.states if s.name == name)

    def code(self, name: str) -> int:
        """1 + state index for states; finals follow the states."""
        for s in self.states:
            if s.name == name:
                return s.code
        return len(self.states) + 1 + self.finals.index(name)


def _dur(v) -> Dist:
    from neorisk_simkit.spec import dist
    from neorisk_simkit.spec.project import parse_duration
    if isinstance(v, Dist):
        return v
    return dist.constant(s=parse_duration(v) / 1_000_000)


class Machine:
    """Builder returned by `p.machine(...)` (and `o.machine(...)`, Task 10)."""

    def __init__(self, name: str, partition: str, *, initial: str, start, config,
                 max_instances: int, fields, reads, refs, max_spawn_depth, **extra):
        self.name, self.partition, self.initial = name, partition, initial
        self.start, self.config = start, config
        self.max_instances, self.max_spawn_depth = int(max_instances), max_spawn_depth
        self.fields = dict(fields or {})
        self.reads, self.refs = dict(reads or {}), dict(refs or {})
        self.extra = extra
        self._states: list[dict] = []
        self._finals: list[str] = []

    def state(self, name: str, *, branch=None, timer=None, repeat=None, max_repeats=None,
              until=None, then=None, join=None, late="ignore", request=None, on_reject=None,
              on_timeout=None, timeout=None, spawn=None) -> Machine:
        for op, d in (("join", join), ("request", request)):
            if d is not None and len(d) != 1:
                raise PackError(f"machine {self.name}: state {name!r}: {op}= takes one "
                                "{target: ...} entry")
        self._states.append({
            "name": name, "branch": branch or {}, "timer": timer or {}, "repeat": repeat,
            "max_repeats": max_repeats, "until": until, "then": then, "join": join or {},
            "late": late, "request": request or {}, "on_reject": on_reject,
            "on_timeout": on_timeout, "timeout": timeout, "spawn": spawn or {}})
        return self

    def final(self, *names: str) -> Machine:
        self._finals.extend(names)
        return self

    def build(self, index: int) -> MachineDef:
        from neorisk_simkit.spec.project import parse_duration
        states = []
        for k, d in enumerate(self._states):
            outcomes = tuple(
                Outcome(t, p, delay, h.as_chain(c) if c is not None else None)
                for t, (p, delay, c) in d["branch"].items())
            rep = d["repeat"]
            if rep is not None:
                rep = (_dur(rep[0]), float(rep[1]),
                       h.as_chain(rep[2]) if rep[2] is not None else None)
            join = next(iter(d["join"].items())) if d["join"] else None
            req = next(iter(d["request"].items())) if d["request"] else None
            states.append(StateDef(
                name=d["name"], code=k + 1, branch=outcomes,
                timers=tuple((t, _dur(v)) for t, v in d["timer"].items()),
                repeat=rep, max_repeats=d["max_repeats"], until=d["until"], then=d["then"],
                join=join, late=d["late"], request=req, on_reject=d["on_reject"],
                on_timeout=d["on_timeout"],
                timeout_us=parse_duration(d["timeout"]) if isinstance(d["timeout"], str)
                else d["timeout"],
                spawn=tuple((c, float(v[0]), v[1], v[2] if len(v) > 2 else 1)
                            for c, v in d["spawn"].items())))
        return MachineDef(
            name=self.name, partition=self.partition, index=index, start=self.start,
            initial=self.initial, states=tuple(states), finals=tuple(self._finals),
            config=self.config, max_instances=self.max_instances,
            fields=MappingProxyType(self.fields), reads=MappingProxyType(self.reads),
            refs=MappingProxyType(self.refs), max_spawn_depth=self.max_spawn_depth,
            **self.extra)


def _chain_acts(chain):
    for part in chain.parts:
        yield part.act
        if part.fallback is not None:
            yield part.fallback


def _state_chains(st):
    for o in st.branch:
        if o.chain is not None:
            yield o.chain
    if st.repeat is not None and st.repeat[2] is not None:
        yield st.repeat[2]
    if st.request is not None and st.request[1].release is not None:
        yield st.request[1].release


def build_machines(pack) -> tuple[tuple[MachineDef, ...], list[str]]:
    errs: list[str] = []
    by_part: dict[str, int] = {}
    out = []
    for b in pack.machines.values():
        i = by_part.get(b.partition, 0)
        by_part[b.partition] = i + 1
        out.append(b.build(i))
    for part, n in by_part.items():
        if n > MAX_MACHINES:
            errs.append(f"partition {part}: more than {MAX_MACHINES} machines")
    names = {m.name: m for m in out}
    for m in out:
        errs += _machine_errors(m, names, pack)
    return tuple(out), errs


def _machine_errors(m: MachineDef, names, pack) -> list[str]:
    e: list[str] = []
    w = f"machine {m.name}"
    declared = [s.name for s in m.states]
    known = set(declared) | set(m.finals)
    if not 1 <= m.max_instances <= MAX_INSTANCES:
        e.append(f"{w}: max_instances must be in [1, {MAX_INSTANCES}]")
    if len(m.states) > MAX_STATES:
        e.append(f"{w}: more than {MAX_STATES} states")
    if m.max_spawn_depth is not None and m.max_spawn_depth < 1:
        e.append(f"{w}: max_spawn_depth must be >= 1")
    if m.initial not in declared:
        e.append(f"{w}: initial state {m.initial!r} is not declared")
    for s in sorted({x for x in declared + list(m.finals)
                     if (declared + list(m.finals)).count(x) > 1}):
        e.append(f"{w}: state {s!r} declared twice")
    for f, decl in m.fields.items():
        if _LOCAL_RE.match(decl) is None or "[" in decl:
            e.append(f"{w}: field {f!r}: {decl!r} is not a scalar local type")
        if f in IMPLICIT_FIELDS:
            e.append(f"{w}: field {f!r} is an implicit instance field (D63)")
    for st in m.states:
        sw = f"{w}: state {st.name!r}"
        targets = [o.target for o in st.branch] + [t for t, _ in st.timers]
        targets += [x for x in (st.then, st.on_reject, st.on_timeout) if x is not None]
        targets += [st.join[0]] if st.join else []
        targets += [st.request[0]] if st.request else []
        for t in targets:
            if t not in known:
                e.append(f"{sw}: unknown target {t!r}")
        main = [bool(st.branch), st.repeat is not None, st.join is not None,
                st.request is not None]
        if sum(main) > 1:
            e.append(f"{sw}: branch, repeat, join and request exclude each other")
        if not any(main) and not st.timers and not st.spawn and st.until is None:
            e.append(f"{sw} has no operation (declare it final)")
        if st.branch:
            nones = [o for o in st.branch if o.p is None]
            if len(nones) > 1:
                e.append(f"{sw}: at most one branch outcome may have p=None")
            fixed = [o.p for o in st.branch if isinstance(o.p, (int, float))]
            total = math.fsum(float(p) for p in fixed)
            pby = [o for o in st.branch if isinstance(o.p, h.PBy)]
            for o in st.branch:
                if isinstance(o.p, h.PBy):
                    e += _pby_errors(sw, o.p, m, pack)
                elif o.p is not None and (not isinstance(o.p, (int, float))
                                          or not 0.0 <= float(o.p) <= 1.0):
                    e.append(f"{sw}: branch {o.target!r}: p must be a float in [0, 1], "
                             "std.p_by(...) or None")
            if not nones and not pby and abs(total - 1.0) > 1e-9:
                e.append(f"{sw}: branch probabilities sum to {total:.6g}; give the unpicked "
                         "mass an explicit otherwise outcome (p=None)")
            if total > 1.0 + 1e-9:
                e.append(f"{sw}: branch probabilities sum to {total:.6g} > 1")
            elif pby:
                e += _pby_sum_errors(sw, total, [o.p for o in pby], bool(nones), m, pack)
        if (st.until is not None or st.max_repeats is not None) and st.then is None:
            e.append(f"{sw}: until/max_repeats need then=")
        if st.until is not None and st.repeat is None:
            e.append(f"{sw}: until needs repeat=")
        if st.repeat is not None and st.repeat[2] is not None and len(st.repeat[2].parts) > 1:
            e.append(f"{sw}: repeat runs one action, not a chain")
        if st.max_repeats is not None and not _is_count(st.max_repeats, REPEAT_CAP):
            e.append(f"{sw}: max_repeats must be an int, std.field, std.col or a "
                     "geometric/uniform_int/categorical Dist")
        if st.join is not None and st.spawn:
            e.append(f"{sw}: a join state cannot declare spawn= (its join would complete with "
                     "zero children first; spawn with std.spawn on the transition into the join)")
        if st.join is not None and not st.timers:
            e.append(f"{sw}: join needs a timer= (its timeout)")
        if st.late not in LATE:
            e.append(f"{sw}: late must be 'ignore' or 'count'")
        if st.request is not None:
            if st.timeout_us is None or st.on_reject is None:
                e.append(f"{sw}: request needs timeout= and on_reject=")
            if st.timers:
                e.append(f"{sw}: request states cannot declare timer= (the owner is "
                         "suspended; use timeout=)")
            req = st.request[1]
            if req.release is None:
                e.append(f"{sw}: request {req.local!r} needs release= (a late granted "
                         "response must be given back, D67)")
            e += _request_errors(sw, req, m, pack)
            e += _field_errors(w, m, (req.shard, req.payload))
        for child, _p, _delay, n in st.spawn:
            e += _spawn_errors(sw, child, m, names)
            e += _count_errors(sw, child, n, names)
            e += _field_errors(w, m, n)
        e += _field_errors(w, m, (st.until, st.max_repeats))
        for chain in _state_chains(st):
            for act in _chain_acts(chain):
                e += _act_errors(w, sw, act, m, names, pack)
    e += _member_errors(w, m, pack)
    return list(dict.fromkeys(e))          # one line per distinct error, first-seen order


def _member_errors(w: str, m: MachineDef, pack) -> list[str]:
    """Cohort machines (Task 10): member values name columns of the member table; `root_init`
    sets declared fields of a root machine (`std.pick_ref` of a declared refs into a ref
    field)."""
    e: list[str] = []
    if m.member_table is not None:
        cols = pack.tables[m.member_table]["cols"]
        e += [f"{w}: member value {c!r} is not a column of {m.member_table!r}"
              for c, _ in m.member_values if c not in cols]
    if m.root_init and not m.root_member:
        e.append(f"{w}: init= is for root machines")
    for f, v in m.root_init:
        if f not in m.fields:
            e.append(f"{w}: init sets unknown field {f!r}")
        elif isinstance(v, h.PickRef):
            if v.refs not in m.refs:
                e.append(f"{w}: std.pick_ref({v.refs!r}): machine {m.name} declares no refs "
                         f"{v.refs!r}")
            if m.fields[f] != "ref":
                e.append(f"{w}: std.pick_ref initializes {f!r}, which is not a ref field")
            if v.parent_share is not None:
                e.append(f"{w}: init {f!r}: a root instance has no parent (parent_share=)")
        else:
            e += _field_errors(w, m, v)
    return e


def _allowed(m: MachineDef, pack) -> tuple[str, ...]:
    """The partitions a machine acts as: its own and the one it acts for (D74)."""
    acts_for = pack.partitions[m.partition].get("acts_for")
    return (m.partition,) if acts_for is None else (m.partition, acts_for)


def _request_errors(sw: str, req: h.Request, m: MachineDef, pack) -> list[str]:
    """A request op names a request boundary sent by the machine's partition (or the one it
    acts for); `ok` is one of its responses; `store` maps response payload fields to declared
    instance fields; the payload gives exactly the boundary's payload fields."""
    b = pack.boundaries.get(req.local)
    if b is None or b["kind"] != "request" or b["frm"] not in _allowed(m, pack):
        return [(f"{sw}: request {req.local!r} is not a request sent by partition "
                 f"{m.partition!r}")]
    e = []
    if req.ok not in b["responses"]:
        e.append(f"{sw}: request {req.local!r}: ok={req.ok!r} is not one of its responses "
                 f"{list(b['responses'])}")
    for rf, f in req.store:
        if rf not in b["response_payload"]:
            e.append(f"{sw}: request {req.local!r}: store key {rf!r} is not a response field")
        if f not in m.fields:
            e.append(f"{sw}: request {req.local!r}: store value {f!r} is not a declared field")
    e += _payload_errors(f"{sw}: request {req.local!r}", [k for k, _ in req.payload],
                         b["payload"])
    return e


def _payload_errors(what: str, given, declared) -> list[str]:
    e = [f"{what}: unknown payload field {k!r}" for k in given if k not in declared]
    return e + [f"{what}: missing payload field {k!r}" for k in declared if k not in given]


def _field_refs(x):
    """Every `std.field` name inside a value (tuples, conditions, nested helpers)."""
    if isinstance(x, h.Field):
        yield x.name
    elif isinstance(x, tuple | list):
        for v in x:
            yield from _field_refs(v)
    elif isinstance(x, h.Cond):
        yield from _field_refs((x.a, x.b))


def _field_errors(w: str, m: MachineDef, x) -> list[str]:
    """`std.field` reads name a declared field or one of the readable implicit fields `rep`,
    `kids`, `jn` (e.g. `max_repeats=std.field("jn")`); writes (`set_field`) are checked apart."""
    return [f"{w}: unknown field {f!r}" for f in _field_refs(x)
            if f not in m.fields and f not in READABLE_IMPLICIT]


def _is_count(v, cap: int) -> bool:
    """A count source (F-18): an int in [0, cap], std.field, std.col, or a geometric /
    uniform_int / categorical Dist."""
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return 0 <= v <= cap
    if isinstance(v, (h.Field, h.Col)):
        return True
    return isinstance(v, Dist) and v.kind in (GEOMETRIC, UNIFORM_INT, CATEGORICAL)


def _count_errors(sw: str, child: str, n, names) -> list[str]:
    """An int count is bounded by the child's instances and the 63-child bitset (D69)."""
    cap = min(MAX_CHILDREN, names[child].max_instances if child in names else MAX_INSTANCES)
    if _is_count(n, cap):
        return []
    return [(f"{sw}: spawn count of {child!r} must be an int in [0, {cap}], std.field, "
             "std.col or a geometric/uniform_int/categorical Dist")]


def _spawn_errors(sw: str, child: str, m: MachineDef, names) -> list[str]:
    if child not in names or names[child].partition != m.partition:
        return [(f"{sw}: spawns unknown machine {child!r} (machines spawn on their own "
                 "partition)")]
    return []


def _pby_sum_errors(sw: str, fixed: float, pbys: list[h.PBy], has_none: bool, m: MachineDef,
                    pack) -> list[str]:
    """Per owner category, the fixed outcomes plus the `std.p_by` outcomes' probabilities must
    not exceed 1, and must be 1 without a p=None outcome (D71; Task 5 review minor 5). Several
    `p_by` outcomes on different columns are judged by their largest probabilities."""
    table = pack.partitions[m.partition]["table"]
    cols = pack.tables[table]["cols"]
    if any(cols.get(b.col) is None or cols[b.col].kind != "cat" for b in pbys):
        return []                                         # reported by _pby_errors

    def p_of(b: h.PBy, cat: str) -> float:
        return dict(b.probs).get(cat, b.otherwise)

    if len({b.col for b in pbys}) == 1:
        sums = {c: fixed + math.fsum(p_of(b, c) for b in pbys)
                for c in cols[pbys[0].col].values}
    else:
        sums = {"(largest)": fixed + math.fsum(max(p_of(b, c) for c in cols[b.col].values)
                                               for b in pbys)}
    out = [f"{sw}: branch probabilities sum to {v:.6g} > 1 for {c!r}"
           for c, v in sums.items() if v > 1.0 + 1e-9]
    if not has_none:
        out += [f"{sw}: branch probabilities sum to {v:.6g} for {c!r}; give the unpicked "
                "mass an explicit otherwise outcome (p=None)"
                for c, v in sums.items() if abs(v - 1.0) > 1e-9]
    return out


def _pby_errors(sw: str, pby: h.PBy, m: MachineDef, pack) -> list[str]:
    table = pack.partitions[m.partition]["table"]
    t = pack.tables[table]["cols"].get(pby.col)
    if t is None or t.kind != "cat":
        return [f"{sw}: std.p_by needs a category column of {table!r}, got {pby.col!r}"]
    return [f"{sw}: std.p_by: {k!r} is not a category of {pby.col!r}"
            for k, _ in pby.probs if k not in t.values]


def _spawns(pm: MachineDef, child: str) -> bool:
    for st in pm.states:
        if any(c == child for c, *_ in st.spawn):
            return True
        if any(isinstance(a, h.Spawn) and a.machine == child
               for chain in _state_chains(st) for a in _chain_acts(chain)):
            return True
    return False


def _act_errors(w: str, sw: str, act, m: MachineDef, names, pack) -> list[str]:
    e: list[str] = []
    allowed = _allowed(m, pack)
    if isinstance(act, ActionSpec):
        if act.state not in allowed:
            e.append(f"{w}: action {act.name} is for partition {act.state!r}, "
                     f"not {m.partition!r}")
        for f, t in act.fields.items():
            if m.fields.get(f) != t:
                e.append(f"{w}: action {act.name} needs instance field {f!r} ({t})")
    elif isinstance(act, h.Emit):
        ev = pack.events.get(act.event)
        if ev is None:
            e.append(f"{sw}: emits unknown event {act.event!r}")
        elif ev["partition"] not in allowed:
            e.append(f"{sw}: event {act.event!r} belongs to partition {ev['partition']!r}")
        e += _field_errors(w, m, act.values)
    elif isinstance(act, h.Spawn):
        e += _spawn_errors(sw, act.machine, m, names)
        e += _count_errors(sw, act.machine, act.n, names)
        e += _field_errors(w, m, (act.n, act.fields))
        child = names.get(act.machine)
        if child is not None:
            for f, v in act.fields:
                if f not in child.fields:
                    e.append(f"{sw}: spawn initializes unknown field {f!r} of {act.machine!r}")
                elif isinstance(v, h.PickRef):
                    if v.refs not in m.refs:
                        e.append(f"{sw}: std.pick_ref({v.refs!r}): machine {m.name} declares "
                                 f"no refs {v.refs!r}")
                    if child.fields[f] != "ref":
                        e.append(f"{sw}: std.pick_ref initializes {f!r} of {act.machine!r}, "
                                 f"which is not a ref field")
                    if v.parent_share is not None and m.fields.get(f) != "ref":
                        e.append(f"{sw}: std.pick_ref(parent_share=) copies the parent's "
                                 f"{f!r}, which is not a ref field of {m.name}")
    elif isinstance(act, h.SendParent):
        if not any(_spawns(pm, m.name) and any(s.join is not None and s.join[1] == act.msg
                                               for s in pm.states)
                   for pm in names.values()):
            e.append(f"{w}: send_parent({act.msg!r}) but no machine that spawns {m.name!r} "
                     f"joins on {act.msg!r}")
    elif isinstance(act, h.LabelAct):
        if m.labels is None:
            e.append(f"{w}: std.label needs o.label(...) on its cohort")
        else:
            cols = pack.events[m.labels]["cols"]
            for col, v in (("role", act.role), ("outcome", act.outcome)):
                if v not in cols[col].values:
                    e.append(f"{sw}: std.label: {v!r} is not a declared {col} of {m.labels}")
    elif isinstance(act, h.SetField):
        if act.name not in m.fields:
            e.append(f"{w}: unknown field {act.name!r}")
        e += _field_errors(w, m, act.value)
    elif isinstance(act, h.Send):
        b = pack.boundaries.get(act.local)
        if b is None or b["kind"] != "message" or b["frm"] not in allowed:
            e.append(f"{sw}: send {act.local!r} is not a message sent by partition "
                     f"{m.partition!r}")
        else:
            e += _payload_errors(f"{sw}: send {act.local!r}", [k for k, _ in act.payload],
                                 b["payload"])
        e += _field_errors(w, m, (act.to, act.payload))
    elif isinstance(act, h.CreateOwner):
        owners = {d["table"] for d in pack.partitions.values() if d["kind"] == "owner"}
        if act.table not in owners or act.table in pack.populations:
            e.append(f"{sw}: create_owner({act.table!r}) needs the table of an owner partition "
                     "without a population")
        e += _field_errors(w, m, act.values)
    return e
