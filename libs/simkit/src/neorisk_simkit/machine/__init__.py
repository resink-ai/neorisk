"""State machines (§04): common behavior with no code, run by a table-driven interpreter.

    m = machine.attach(kind, "payment", initial="authorized")
    m.state("authorized",
            branch={"captured": (0.93, dist.lognormal(median_s=3600), "capture"),
                    "otherwise": (0.07, None, None)},           # unpicked mass: stay
            timer={"expired": "7d"})                           # earliest wins; leaving cancels
    m.state("captured", repeat=(dist.exp(mean_days=9), 0.04, "refund"), max_repeats=3)
    m.state("expired", retire=True)

Operations per state, all evaluated on entering it:
    branch   {target: (p, delay, action)}; "otherwise" is the unpicked mass (its p may be
             None: the remainder). p and delays may be "cfg.<field>" to read the run config
    timer    {target: delay | (delay, action)}; leaving bumps a generation, stale timers drop
    repeat   (delay, p, action) with max_repeats; `until` (a cond) is evaluated after each
             committed action, then go to `then`
    spawn    Spawn(kind, n, ...): create child owners now (depth bounded by the engine)
    join     {target: (message, "all_spawned" | n)} with join_timeout=(delay, target) and
             late="ignore" | "count"; zero children fires at once; duplicates are suppressed
    request  {target: Request(to, action, timeout, on_reject, ...)}; timeout and a rejection
             branch are mandatory
    then     Then(a, b, fallback=c): each part is its own atomic step; if b rejects, a stays
             committed and c runs

Actions are names of the kind's actions (handwritten or std), or (name, {payload}); the
interpreter calls them inline. Children notify their parent with `notify_parent(ctx, msg)`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from neorisk_simkit.engine.loop import Reject
from neorisk_simkit.spec import dist as D
from neorisk_simkit.spec.pack import Kind, PackError

Action = Any       # an action name, (name, payload), a Then, or None


@dataclass(frozen=True)
class Then:
    first: Action
    second: Action
    fallback: Action = None


@dataclass(frozen=True)
class Spawn:
    kind: str
    n: int | D.Dist = 1
    cohort: str | None = None
    init: Callable[..., dict] | None = None          # (ctx, s, i) -> creation fields


@dataclass(frozen=True)
class Request:
    to: tuple[str, Any] | Callable[..., int]          # (kind, key) or (ctx, s) -> partition
    action: str
    timeout: str | float
    on_reject: str
    on_timeout: str | None = None
    payload: dict | Callable[..., dict] = field(default_factory=dict)
    then: Action = None                               # runs on an ok reply, before entering


@dataclass
class State:
    name: str
    branch: dict[str, tuple] = field(default_factory=dict)
    timer: dict[str, Any] = field(default_factory=dict)
    repeat: tuple | None = None
    max_repeats: int | None = None
    until: Callable[..., bool] | None = None
    then: str | None = None
    spawn: list[Spawn] = field(default_factory=list)
    join: dict[str, tuple[str, Any]] = field(default_factory=dict)
    join_timeout: tuple[Any, str] | None = None
    late: str = "ignore"
    request: dict[str, Request] = field(default_factory=dict)
    on_enter: Action = None
    on_reject: str | None = None
    retire: bool = False

    def targets(self) -> list[str]:
        t = [k for k in self.branch if k != "otherwise"] + list(self.timer) + list(self.join)
        t += list(self.request) + [r.on_reject for r in self.request.values()]
        t += [r.on_timeout for r in self.request.values() if r.on_timeout]
        t += [x for x in (self.then, self.on_reject) if x]
        if self.join_timeout:
            t.append(self.join_timeout[1])
        return t


# --- conditions for `until` (typed helpers, never expressions) ----------------------------

class cond:
    @staticmethod
    def repeats_ge(n: int) -> Callable[..., bool]:
        return lambda ctx, s, loc: loc["repeats"] >= n

    @staticmethod
    def attr_ge(name: str, other: str | float) -> Callable[..., bool]:
        """`s.<name> >= s.<other>` (or a number)."""
        def f(ctx, s, loc):
            rhs = getattr(s, other) if isinstance(other, str) else other
            return getattr(s, name) >= rhs
        return f

    @staticmethod
    def flag(key: str) -> Callable[..., bool]:
        """A flag an action set in the machine's private state (`machine.local(ctx, m)`)."""
        return lambda ctx, s, loc: bool(loc.get(key))


def notify_parent(ctx, msg: str) -> None:
    """Send `msg` to the partition that created this one (for its `join`)."""
    if ctx.part.parent is None:
        raise PackError(f"{ctx._where()}: notify_parent in a partition without a parent")
    ctx.send(ctx.part.parent, "mx_child", msg=msg, child=ctx.part.ordinal)


def local(ctx, machine: str) -> dict:
    return _loc(ctx.part, machine)


def _loc(part, name: str) -> dict:
    loc = part.local.get(name)
    if loc is None:
        loc = part.local[name] = {"state": None, "gen": 0, "repeats": 0, "spawned": 0,
                                  "got": {}, "joined": set(), "req": None}
    return loc


class Machine:
    def __init__(self, kind: Kind, name: str, initial: str, cohort: str | None = None):
        self.kind, self.name, self.initial = kind, name, initial
        self.states: dict[str, State] = {}
        p = kind.process(name, start=f"mx_{name}_start")
        p.machine, p.cohort = self, cohort
        p.action(self._start, name=f"mx_{name}_start")
        p.action(self._fire, name=f"mx_{name}_fire")
        p.action(self._reply, name=f"mx_{name}_reply")
        if "mx_child" not in kind.actions:
            kind.process("mx_children").action(_child, name="mx_child")

    def state(self, name: str, **ops: Any) -> State:
        if name in self.states:
            raise PackError(f"machine {self.name}: duplicate state {name!r}")
        spawn = ops.pop("spawn", [])
        st = State(name, spawn=[spawn] if isinstance(spawn, Spawn) else list(spawn), **ops)
        self.states[name] = st
        return st

    # --- validation ---------------------------------------------------------------------
    def problems(self) -> list[str]:
        errs, where = [], f"{self.kind.name}.{self.name}"
        if self.initial not in self.states:
            errs.append(f"{where}: initial state {self.initial!r} is not defined")
        for st in self.states.values():
            for t in st.targets():
                if t not in self.states:
                    errs.append(f"{where}.{st.name}: unknown target state {t!r}")
            ps = [v[0] for v in st.branch.values()]
            if ps and all(isinstance(p, (int, float)) for p in ps) and abs(sum(ps) - 1) > 1e-9:
                errs.append(f"{where}.{st.name}: branch probabilities must sum to 1 "
                            f"(use 'otherwise' for the unpicked mass)")
            if any(p is None for k, (p, *_) in st.branch.items() if k != "otherwise"):
                errs.append(f"{where}.{st.name}: only 'otherwise' may leave p as None")
            if st.until is not None and st.repeat is None:
                errs.append(f"{where}.{st.name}: until needs repeat")
            if st.join and st.join_timeout is None:
                errs.append(f"{where}.{st.name}: join needs join_timeout")
            if st.late not in ("ignore", "count"):
                errs.append(f"{where}.{st.name}: late must be 'ignore' or 'count'")
            for r in st.request.values():
                if not r.timeout or not r.on_reject:
                    errs.append(f"{where}.{st.name}: request needs a timeout and on_reject")
            for a in _actions(st):
                if a not in self.kind.actions:
                    errs.append(f"{where}.{st.name}: unknown action {a!r}")
        return errs

    # --- interpreter --------------------------------------------------------------------
    def _start(self, ctx, s, cmd):
        self._enter(ctx, s, self.initial)

    def _enter(self, ctx, s, name: str) -> None:
        loc = _loc(ctx.part, self.name)
        st = self.states[name]
        loc["state"], loc["repeats"], loc["req"] = name, 0, None
        loc["gen"] += 1
        gen, rng = loc["gen"], ctx.rng
        _run(ctx, st.on_enter)
        if st.retire:
            ctx.retire()
            return
        if st.branch:
            u, acc = rng.random(), 0.0
            for target, (p, delay, act) in st.branch.items():
                acc = 1.0 if p is None else acc + _param(ctx, p)
                if u < acc:
                    if target != "otherwise":
                        self._schedule(ctx, _delay(ctx, delay), gen, "go", target, act)
                    break
        for target, spec in st.timer.items():
            delay, act = spec if isinstance(spec, tuple) else (spec, None)
            self._schedule(ctx, _delay(ctx, delay), gen, "go", target, act)
        if st.repeat is not None:
            self._schedule(ctx, _delay(ctx, st.repeat[0]), gen, "repeat", None, None)
        for sp in st.spawn:
            n = int(D.draw(sp.n, rng)) if isinstance(sp.n, D.Dist) else int(sp.n)
            for i in range(n):
                init = sp.init(ctx, s, loc["spawned"] + i) if sp.init else {}
                ctx.create(sp.kind, cohort=sp.cohort, **init)
            loc["spawned"] += n
        for target, r in st.request.items():
            to = r.to(ctx, s) if callable(r.to) else ctx.find(*r.to)
            payload = r.payload(ctx, s) if callable(r.payload) else dict(r.payload)
            loc["req"] = (ctx.request(to, r.action, reply=f"mx_{self.name}_reply",
                                      timeout=D.parse_duration(r.timeout), **payload), target)
        if st.join:
            if st.join_timeout is not None:
                delay, target = st.join_timeout
                self._schedule(ctx, D.draw(delay, rng), gen, "go", target, None)
            self._try_join(ctx, s, st, loc)

    def _schedule(self, ctx, delay: float, gen: int, op: str, target, act) -> None:
        ctx.after(delay, f"mx_{self.name}_fire", gen=gen, op=op, target=target, act=act)

    def _fire(self, ctx, s, cmd):
        loc = _loc(ctx.part, self.name)
        if cmd.gen != loc["gen"]:
            return ctx.commit()                      # stale: the state was left
        st = self.states[loc["state"]]
        if cmd.op == "go":
            res = _run(ctx, cmd.act)
            if isinstance(res, Reject):
                return self._rejected(ctx, s, st, res)
            return self._enter(ctx, s, cmd.target)
        loc["repeats"] += 1                          # repeat
        delay, p, act = st.repeat
        if ctx.rng.random() < _param(ctx, p):
            res = _run(ctx, act)
            if not isinstance(res, Reject) and st.until is not None and st.until(ctx, s, loc):
                return self._enter(ctx, s, st.then) if st.then else None
        if st.max_repeats is not None and loc["repeats"] >= st.max_repeats:
            return self._enter(ctx, s, st.then) if st.then else None
        self._schedule(ctx, _delay(ctx, delay), loc["gen"], "repeat", None, None)

    def _rejected(self, ctx, s, st: State, res: Reject):
        if st.on_reject:
            return self._enter(ctx, s, st.on_reject)
        return res                                    # nothing written: stay, idle

    def _reply(self, ctx, s, cmd):
        loc = _loc(ctx.part, self.name)
        if loc["req"] is None or loc["req"][0] != cmd.req:
            return ctx.commit()                      # the state was left meanwhile
        target = loc["req"][1]
        r = self.states[loc["state"]].request[target]
        if cmd.ok:
            _run(ctx, r.then, cmd.payload)
            return self._enter(ctx, s, target)
        if cmd.status == "timeout" and r.on_timeout:
            return self._enter(ctx, s, r.on_timeout)
        return self._enter(ctx, s, r.on_reject)

    def _try_join(self, ctx, s, st: State, loc: dict) -> None:
        for target, (msg, expected) in st.join.items():
            want = loc["spawned"] if expected == "all_spawned" else int(expected)
            if len(loc["got"].get(msg, ())) >= want:
                loc["joined"].add(msg)
                return self._enter(ctx, s, target)
        return None


def _param(ctx, v: Any) -> Any:
    """A literal, or "cfg.<field>" read from the run's config."""
    return getattr(ctx.cfg, v[4:]) if isinstance(v, str) and v.startswith("cfg.") else v


def _delay(ctx, d: Any) -> float:
    """A delay: a Dist, a duration ("7d"), a number of seconds, or "cfg.<field>" holding a
    number of days (config is written in days) or any of the above."""
    if isinstance(d, str) and d.startswith("cfg."):
        v = _param(ctx, d)
        return float(v) * 86_400.0 if isinstance(v, (int, float)) else D.draw(v, ctx.rng)
    return D.draw(d, ctx.rng)


def _child(ctx, s, cmd):
    """A child's message: count it once per child ordinal; join if a waiting state is done."""
    for proc in ctx.part.kind.processes.values():
        m = proc.machine
        if m is None or proc.name not in ctx.part.local:
            continue
        loc = ctx.part.local[proc.name]
        st = m.states.get(loc["state"])
        waits = any(msg == cmd.msg for msg, _ in (st.join.values() if st else ()))
        if cmd.msg in loc["joined"] and not waits:
            late = any(x.late == "count" for x in m.states.values()
                       if any(msg == cmd.msg for msg, _ in x.join.values()))
            return ctx.reject("late_child_message") if late else ctx.commit()
        got = loc["got"].setdefault(cmd.msg, set())
        if cmd.child in got:
            return ctx.reject("duplicate_child_message")
        got.add(cmd.child)
        if waits:
            m._try_join(ctx, s, st, loc)
        return ctx.commit()
    return ctx.reject("no_machine_waits")


def _call_parts(a: Action):
    if a is None:
        return []
    if isinstance(a, Then):
        return _call_parts(a.first) + _call_parts(a.second) + _call_parts(a.fallback)
    return [a[0] if isinstance(a, tuple) else a]


def _actions(st: State) -> list[str]:
    acts = [v[2] for v in st.branch.values()]
    acts += [v[1] for v in st.timer.values() if isinstance(v, tuple)]
    acts += [st.repeat[2]] if st.repeat else []
    acts += [st.on_enter] + [r.then for r in st.request.values()]
    return [n for a in acts for n in _call_parts(a)]


def _run(ctx, a: Action, extra: dict | None = None):
    """Run an action spec inline. `Then`: if the second part rejects, the first stays
    committed and the fallback runs."""
    if a is None:
        return None
    if isinstance(a, Then):
        r = _run(ctx, a.first, extra)
        if isinstance(r, Reject):
            return r
        r2 = _run(ctx, a.second, extra)
        if isinstance(r2, Reject):
            _run(ctx, a.fallback, extra)
        return None
    name, payload = a if isinstance(a, tuple) else (a, {})
    return ctx.call(name, **{**(extra or {}), **payload})


def attach(kind: Kind, name: str, *, initial: str, cohort: str | None = None) -> Machine:
    return Machine(kind, name, initial, cohort)
