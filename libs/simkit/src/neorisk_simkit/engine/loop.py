"""The event loop: one heap, one thread, one total order.

A command is `(time, priority, push_seq, partition_id, action, payload, cause_id, meta)`. The
loop pops the earliest one and runs the addressed partition's action with a `Ctx`. Rows get
`seq` from one global counter as they are emitted, so sorting rows by `seq` reproduces
execution order, which is `(event_time, priority, seq)`.

Actions follow validate → commit: `ctx.reject(reason)` is legal only before the action's first
effect (emit, schedule, create, insert, label). Debug mode also snapshots the partition state
and fails the run if a rejected action changed it.
"""

from __future__ import annotations

import copy
import heapq
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import numpy as np

from neorisk_simkit.engine import rng as rngs
from neorisk_simkit.spec.pack import MESSAGE, TIMER, Action, Kind
from neorisk_simkit.spec.plan import NS_SPAN, Plan
from neorisk_simkit.spec.types import accepts

DAY = 86_400.0
HOUR = 3_600.0
MINUTE = 60.0


class SimError(RuntimeError):
    """A run failed: a contract violation, a guard, or an exception in pack code."""


@dataclass
class RunConfig:
    seed: int = 7
    days: float = 30.0
    start: datetime = datetime(2026, 1, 1, tzinfo=UTC)
    warmup_days: float = 0.0          # rows before this are generated but not exported
    mode: str = "time"                # time: stop at the horizon | population: run cases out
    max_events: int = 1_000_000
    max_case_steps: int = 100_000     # population mode: a case is censored after this many
    debug: bool = False


@dataclass(frozen=True)
class Reject:
    reason: str


COMMIT = None
RESERVED = frozenset({"action", "t", "payload", "status", "reason", "sender", "req", "ok"})


class Cmd:
    """The command an action runs for. Payload fields read as attributes (`cmd.sku`)."""
    __slots__ = ("action", "payload", "reason", "req", "sender", "status", "t")

    def __init__(self, action: str, t: float, payload: dict, sender: int | None = None,
                 status: str = "ok", reason: str | None = None, req: int | None = None):
        self.action, self.t, self.payload = action, t, payload
        self.sender, self.status, self.reason, self.req = sender, status, reason, req

    def __getattr__(self, k: str) -> Any:
        try:
            return self.payload[k]
        except KeyError:
            raise AttributeError(f"command {self.action!r} has no field {k!r}") from None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class Part:
    __slots__ = (
        "children",
        "cohort",
        "created_at",
        "depth",
        "key",
        "kind",
        "local",
        "ns",
        "ordinal",
        "parent",
        "pending",
        "pid",
        "retired_at",
        "rngs",
        "state",
        "steps",
    )

    def __init__(self, pid: int, kind: Kind, state: Any, key: int, ns: int, depth: int,
                 created_at: float, cohort: str | None):
        self.pid, self.kind, self.state, self.key, self.ns = pid, kind, state, key, ns
        self.depth, self.created_at, self.cohort = depth, created_at, cohort
        self.retired_at: float | None = None
        self.steps = 0
        self.rngs: dict[str, np.random.Generator] = {}
        self.pending: dict[int, str] = {}           # open request id -> reply action
        self.children: Counter = Counter()          # kind -> ordinal, for child keys
        self.local: dict[str, dict] = {}            # process -> private state (ctx.local)
        self.parent: int | None = None              # the creating partition, if any
        self.ordinal = 0                            # among the parent's children of its kind


@dataclass
class Stats:
    late_messages: int = 0
    late_replies: int = 0
    commands: int = 0
    rejections: Counter = field(default_factory=Counter)   # (kind, action, reason) -> n


class _Base:
    """What sources and actions share: creating partitions and inserting entity rows."""
    _e: Engine
    ns: int

    @property
    def cfg(self) -> Any:
        return self._e.cfg

    @property
    def shared(self) -> SimpleNamespace:
        return self._e.shared

    @property
    def days(self) -> float:
        return self._e.run.days

    @property
    def horizon(self) -> float:
        """The run end in seconds (infinite in population mode)."""
        return self._e.horizon

    def new_id(self, space: str) -> int:
        """The next sequential id in `space` (for ids without an entity table, e.g. sessions)."""
        return self._e._next_id(space, self.ns)

    def find(self, kind: str, key: Any) -> int:
        """The partition id a source registered as `create(kind, ..., key=key)`."""
        try:
            return self._e.named[(kind, key)]
        except KeyError:
            raise SimError(f"no {kind!r} partition with key {key!r}") from None


class SourceCtx(_Base):
    def __init__(self, e: Engine, name: str, ns: int, cohort: str | None = None):
        self._e, self.name, self.ns, self.cohort = e, name, ns, cohort
        self.rng = rngs.stream(e.run.seed, rngs.key("source", ns, name))
        self._n: Counter = Counter()

    def create(self, kind: str, *, at: float = 0.0, key: Any = None, cohort: str | None = None,
               **init: Any) -> int | None:
        """Create a partition that starts at `at`; returns None if `at` is past the horizon."""
        e = self._e
        if at >= e.horizon:
            return None
        self._n[kind] += 1
        pkey = rngs.key("source", self.ns, self.name, kind, self._n[kind])
        return e._create(e.plan.kinds[kind], init, self.ns, pkey, 0, at, None, key,
                         e._cohort(cohort or self.cohort, self.ns))

    def insert(self, table: str, *, at: float = 0.0, **cols: Any) -> int:
        """An entity row created at `at` (sources may pre-assign ids for later arrivals)."""
        return self._e._insert(table, cols, self.ns, at)

    def share(self, name: str, **arrays: np.ndarray) -> None:
        """Read-only shared inputs, visible to every action as `ctx.shared.<name>.<array>`."""
        for a in arrays.values():
            if isinstance(a, np.ndarray):
                a.setflags(write=False)
        setattr(self._e.shared, name, SimpleNamespace(**arrays))


class Ctx(_Base):
    """The action context: one partition, one command, one point in time."""

    def __init__(self, e: Engine):
        self._e = e
        self.part: Part
        self.action: Action
        self.cmd: Cmd
        self.cause: int | None = None
        self._effects = 0
        self._reply: dict | None = None

    # --- reading ------------------------------------------------------------------------
    @property
    def now(self) -> float:
        return self._e.now

    @property
    def self_id(self) -> int:
        return self.part.pid

    @property
    def ns(self) -> int:
        return self.part.ns

    @property
    def rng(self) -> np.random.Generator:
        p, proc = self.part, self.action.process
        g = p.rngs.get(proc)
        if g is None:
            g = p.rngs[proc] = rngs.stream(self._e.run.seed, p.key, rngs.key(proc))
        return g

    @property
    def local(self) -> dict:
        """Private state of the running process in this partition (for overlay processes,
        whose state is not part of the kind's state class)."""
        return self.part.local.setdefault(self.action.process, {})

    def call(self, action: str, **payload: Any) -> Any:
        """Run another action of this partition inline, inside the same atomic step (an
        overlay reaching a base extension point). Returns that action's result."""
        act = self._act(self.part.kind, action)
        saved = self.action, self.cmd, self._effects
        self.action, self.cmd, self._effects = act, Cmd(action, self._e.now, payload), 0
        try:
            return act.fn(self, self.part.state, self.cmd)
        finally:
            self.action, self.cmd = saved[:2]
            self._effects += saved[2]

    # --- outcomes -----------------------------------------------------------------------
    def commit(self) -> None:
        return COMMIT

    def reject(self, reason: str) -> Reject:
        if self._effects:
            raise SimError(f"{self._where()}: rejected ({reason!r}) after its first write")
        return Reject(reason)

    def reply(self, **payload: Any) -> None:
        """Answer the request this action is handling (the requester sees status 'ok')."""
        self._reply = payload
        return COMMIT

    def decline(self, reason: str, **payload: Any) -> None:
        """Commit this action (its decision rows stay) but answer the request as 'rejected'.
        Use `reject` instead when nothing was written."""
        self._reply = {**payload, "__status": "rejected", "__reason": reason}
        return COMMIT

    # --- effects ------------------------------------------------------------------------
    def emit(self, event: str, **cols: Any) -> int:
        e = self._e
        self._effects += 1
        try:
            names, lists = e._ev[event]
        except KeyError:
            raise SimError(f"{self._where()}: emits undeclared event {event!r}") from None
        seq = e.seq = e.seq + 1
        lists["event_id"].append(seq)
        lists["event_time"].append(e.now)
        lists["seq"].append(seq)
        lists["partition_id"].append(self.part.pid)
        lists["cause_id"].append(self.cause)
        lists["action_id"].append(self.action.id)
        for c in names:
            lists[c].append(cols.pop(c, None))
        if cols:
            raise SimError(f"{self._where()}: {event} has no columns {sorted(cols)}")
        if e.run.debug:
            e._check_row(event, names, lists, self._where())
        self.last = seq
        return seq

    def after(self, delay: float, action: str, **payload: Any) -> None:
        if delay < 0:
            raise SimError(f"{self._where()}: negative delay {delay}")
        self.at(self._e.now + delay, action, **payload)

    def at(self, t: float, action: str, **payload: Any) -> None:
        """A timer to this partition (TIMER priority unless the action declares one)."""
        if t < self._e.now:
            raise SimError(f"{self._where()}: timer {action!r} scheduled in the past")
        act = self._act(self.part.kind, action)
        self._push(t, act, TIMER, self.part.pid, payload, None)

    def send(self, pid: int, action: str, **payload: Any) -> None:
        """A message to another owner, delivered after the target's latency (≥ δ)."""
        e = self._e
        target = e._part(pid)
        act = self._act(target.kind, action)
        lat = target.kind.latency
        t = e.now + self.rng.uniform(lat.min, lat.hi)
        self._push(t, act, MESSAGE, pid, copy.deepcopy(payload), ("msg", self.part.pid))

    def request(self, pid: int, action: str, *, reply: str, timeout: float | None = None,
                latency: float | None = None, **payload: Any) -> int:
        """Ask partition `pid` (usually a shard) to run `action`; the answer arrives as
        `reply` on this partition at now + latency, with `cmd.status` ok | rejected | timeout."""
        e = self._e
        target = e._part(pid)
        act = self._act(target.kind, action)
        self._act(self.part.kind, reply)
        lat = target.kind.latency
        if latency is None:
            latency = self.rng.uniform(lat.min, lat.hi)
        elif latency < lat.min:
            raise SimError(f"{self._where()}: latency {latency} is below δ={lat.min} of "
                           f"{target.kind.name}")
        e.req += 1
        self.part.pending[e.req] = reply
        meta = ("req", self.part.pid, e.req, reply, latency)
        self._push(e.now, act, MESSAGE, pid, copy.deepcopy(payload), meta)
        if timeout is not None:
            self._push(e.now + timeout, self._act(self.part.kind, reply), TIMER, self.part.pid,
                       {}, ("timeout", e.req))
        return e.req

    def create(self, kind: str, *, key: Any = None, cohort: str | None = None,
               **init: Any) -> int:
        """Create a partition (a creation message processed now). Depth is bounded."""
        e, part = self._e, self.part
        depth = part.depth + 1
        proc = part.kind.processes[self.action.process]
        if depth > proc.max_spawn_depth:
            raise SimError(f"{self._where()}: spawn depth {depth} exceeds max_spawn_depth "
                           f"{proc.max_spawn_depth} of process {proc.name!r}")
        part.children[kind] += 1
        pkey = rngs.key(part.key, kind, part.children[kind])
        self._effects += 1
        pid = e._create(e.plan.kinds[kind], init, part.ns, pkey, depth, e.now, self.last,
                        key, e._cohort(cohort or part.cohort, part.ns))
        child = e.parts[pid]
        child.parent, child.ordinal = part.pid, part.children[kind]
        return pid

    def insert(self, table: str, **cols: Any) -> int:
        self._effects += 1
        return self._e._insert(table, cols, self.part.ns, self._e.now)

    def label(self, target_id: int, role: str, *, outcome: str | None = None,
              campaign_id: int | None = None, available_at: float | None = None) -> None:
        """A hidden label row; the last one written for a target is its final label."""
        self._effects += 1
        e = self._e
        for k, v in (("target_id", target_id), ("role", role), ("outcome", outcome),
                     ("campaign_id", campaign_id), ("labeled_at", e.now),
                     ("label_available_at", e.now if available_at is None else available_at)):
            e.labels[k].append(v)

    def retire(self) -> None:
        """End this partition after the action; later commands to it are dropped as late."""
        self._effects += 1
        self.part.retired_at = self._e.now

    # --- internals ----------------------------------------------------------------------
    def _act(self, kind: Kind, name: str) -> Action:
        try:
            return kind.actions[name]
        except KeyError:
            raise SimError(f"{self._where()}: {kind.name} has no action {name!r}") from None

    def _push(self, t: float, act: Action, default_prio: int, pid: int, payload: dict,
              meta: tuple | None) -> None:
        self._effects += 1
        if payload and not RESERVED.isdisjoint(payload):
            raise SimError(f"{self._where()}: payload keys {sorted(RESERVED & set(payload))} "
                           f"shadow command fields; rename them")
        prio = default_prio if act.priority is None else act.priority
        self._e._push(t, prio, pid, act.name, payload, self.last, meta)

    def _where(self) -> str:
        p = self.part
        return (f"{p.kind.name}.{self.action.name} (process {self.action.process!r}, "
                f"partition {p.pid}, t={self._e.now:.3f})")


class Engine:
    def __init__(self, plan: Plan, cfg: Any, run: RunConfig):
        self.plan, self.cfg, self.run = plan, cfg, run
        self.now = 0.0
        self.horizon = run.days * DAY if run.mode == "time" else float("inf")
        self.heap: list[tuple] = []
        self.seq = self.req = self.pushes = 0
        self.parts: dict[int, Part] = {}
        self.named: dict[tuple[str, Any], int] = {}
        self.shared = SimpleNamespace()
        self.stats = Stats()
        self._ids: Counter = Counter()
        self._ev = {name: (list(t.cols), {c: [] for c in t.columns() if c != "event_type"})
                    for name, t in plan.events.items()}
        self._ent = {name: {c: [] for c in t.columns()} for name, t in plan.entities.items()}
        self.labels: dict[str, list] = {c: [] for c in (
            "target_id", "role", "outcome", "campaign_id", "labeled_at", "label_available_at")}
        self.snapshot: dict[str, list[dict]] | None = None
        self._cohorts = {c.name: c for o in plan.overlays for c in o.cohorts}

    # --- allocation ---------------------------------------------------------------------
    def _next_id(self, space: str, ns: int) -> int:
        self._ids[(space, ns)] += 1
        return ns * NS_SPAN + self._ids[(space, ns)]

    def _create(self, kind: Kind, init: dict, ns: int, pkey: int, depth: int, t: float,
                cause: int | None, key: Any, cohort: str | None) -> int:
        pid = self._next_id("partition", ns)
        part = Part(pid, kind, kind.state(**init), pkey, ns, depth, t, cohort)
        self.parts[pid] = part
        if key is not None:
            if (kind.name, key) in self.named:
                raise SimError(f"duplicate {kind.name} partition key {key!r}")
            self.named[(kind.name, key)] = pid
        for proc in self._starting(part):
            act = kind.actions[proc.start]
            self._push(t, MESSAGE if act.priority is None else act.priority, pid, act.name, {},
                       cause, None)
        return pid

    def _cohort(self, name: str | None, ns: int) -> str | None:
        if name is not None and (name not in self._cohorts or self._cohorts[name].ns != ns):
            raise SimError(f"cohort {name!r} is not declared by this overlay")
        return name

    def _starting(self, part: Part):
        coh = self._cohorts.get(part.cohort)
        for proc in part.kind.processes.values():
            if proc.start is None:
                continue
            owner = getattr(proc, "cohort", None)
            if owner is not None and owner != part.cohort:
                continue
            if coh is not None and proc.name in coh.suppress:
                continue
            yield proc

    def _insert(self, table: str, cols: dict, ns: int, t: float) -> int:
        try:
            spec, lists = self.plan.entities[table], self._ent[table]
        except KeyError:
            raise SimError(f"insert into undeclared entity table {table!r}") from None
        rid = self._next_id(table, ns)
        lists[spec.key].append(rid)
        lists["created_at"].append(t)
        for c in spec.cols:
            lists[c].append(cols.pop(c, None))
        if cols:
            raise SimError(f"entity {table} has no columns {sorted(cols)}")
        if self.run.debug:
            self._check_row(table, list(spec.cols), lists, f"insert into {table}")
        return rid

    def _push(self, t: float, prio: int, pid: int, action: str, payload: dict,
              cause: int | None, meta: tuple | None) -> None:
        if t >= self.horizon:
            return
        self.pushes += 1
        heapq.heappush(self.heap, (t, prio, self.pushes, pid, action, payload, cause, meta))

    def _part(self, pid: int) -> Part:
        try:
            return self.parts[pid]
        except KeyError:
            raise SimError(f"no partition {pid}") from None

    def _check_row(self, table: str, names: list[str], lists: dict, where: str) -> None:
        t = self.plan.events.get(table) or self.plan.entities[table]
        for c in names:
            v = lists[c][-1]
            if not accepts(t.cols[c], v):
                raise SimError(f"{where}: {table}.{c} = {v!r} does not fit {t.cols[c].kind}"
                               f"{'' if t.cols[c].nullable else ' (not null)'}")

    # --- the loop -----------------------------------------------------------------------
    def run_sources(self) -> None:
        for src, ns in self.plan.sources:
            cohort = getattr(src, "cohort", None)
            src.fn(SourceCtx(self, src.name, ns, cohort))

    def loop(self) -> None:
        heap, parts, run, stats = self.heap, self.parts, self.run, self.stats
        ctx = Ctx(self)
        warm = run.warmup_days * DAY
        pop = heapq.heappop
        while heap:
            t, _, _, pid, action, payload, cause, meta = pop(heap)
            if warm and self.snapshot is None and t >= warm:
                self._take_snapshot()
            self.now = t
            part = parts[pid]
            if part.retired_at is not None:
                stats.late_messages += 1
                continue
            sender, status, reason, req = None, "ok", None, None
            if meta is not None:
                tag = meta[0]
                if tag == "reply":
                    _, req, status, reason, sender = meta
                    if part.pending.pop(req, None) is None:
                        stats.late_replies += 1          # it already timed out
                        continue
                elif tag == "timeout":
                    req = meta[1]
                    if part.pending.pop(req, None) is None:
                        continue                         # answered in time
                    status = "timeout"
                else:
                    sender = meta[1]
            stats.commands += 1
            if part.cohort is not None:
                action = self._cohorts[part.cohort].redirect.get(action, action)
            self._dispatch(ctx, part, part.kind.actions[action],
                           Cmd(action, t, payload, sender, status, reason, req), cause, meta)
            if self.seq > run.max_events:
                raise SimError(f"max_events={run.max_events} exceeded at t={t:.3f} by "
                               f"{part.kind.name}.{action}; a runaway pack, or raise the guard")
            if run.mode == "population" and part.steps > run.max_case_steps:
                part.retired_at = t

    def _dispatch(self, ctx: Ctx, part: Part, act: Action, cmd: Cmd, cause: int | None,
                  meta: tuple | None) -> None:
        ctx.part, ctx.action, ctx.cmd = part, act, cmd
        ctx.cause = ctx.last = cause
        ctx._effects, ctx._reply = 0, None
        before = copy.deepcopy(part.state) if self.run.debug else None
        try:
            res = act.fn(ctx, part.state, cmd)
        except SimError:
            raise
        except Exception as exc:
            raise SimError(f"{ctx._where()} raised {type(exc).__name__}: {exc}") from exc
        part.steps += 1
        rejected = isinstance(res, Reject)
        if rejected:
            self.stats.rejections[(part.kind.name, act.name, res.reason)] += 1
            if before is not None and before != part.state:
                raise SimError(f"{ctx._where()}: rejected ({res.reason!r}) after changing "
                               f"its partition state")
        if meta is not None and meta[0] == "req":
            _, requester, req, reply, latency = meta
            payload = ctx._reply or {}
            if rejected:
                st, why, payload = "rejected", res.reason, {}
            elif "__status" in payload:
                st, why = payload.pop("__status"), payload.pop("__reason")
                self.stats.rejections[(part.kind.name, act.name, why)] += 1
            else:
                st, why = "ok", None
            self._push(self.now + latency, MESSAGE, requester, reply, payload, ctx.last,
                       ("reply", req, st, why, part.pid))

    def _take_snapshot(self) -> None:
        snap: dict[str, list[dict]] = {}
        for p in self.parts.values():
            if p.retired_at is None and p.created_at <= self.now:
                row = {"partition_id": p.pid, **_state_row(p.state)}
                snap.setdefault(p.kind.name, []).append(row)
        self.snapshot = snap


def _state_row(state: Any) -> dict:
    d = state.__dict__ if hasattr(state, "__dict__") else {}
    return {k: v for k, v in d.items() if isinstance(v, (int, float, str, bool, type(None)))}
