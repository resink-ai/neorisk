"""The state-machine interpreter: every operation and its decided edge cases."""

from dataclasses import dataclass

import polars as pl
import pytest

from neorisk_simkit import machine as mx
from neorisk_simkit.engine import DAY, RunConfig, simulate
from neorisk_simkit.machine import Request, Spawn, Then, cond
from neorisk_simkit.spec import Latency, Pack, build_plan, dist, i64, opt, text, validate


@dataclass
class Case:
    n: int = 0
    ok_desk: bool = True


@dataclass
class Desk:
    pass


def _pack(define_machine, *, cases=1) -> Pack:
    p = Pack("m")
    p.event("step", cols={"what": text(), "n": opt(i64())})
    k = p.owner("case", state=Case)
    desk = p.shard("desk", state=Desk, latency=Latency(1.0, 1.0))
    acts = k.process("acts")
    for name in ("a", "b", "c", "capture", "refund", "late_one"):
        def emit(ctx, s, cmd, name=name):
            s.n += 1
            ctx.emit("step", what=name, n=s.n)
        acts.action(emit, name=name)

    @acts.action
    def nope(ctx, s, cmd):
        return ctx.reject("nope")

    @acts.action
    def report(ctx, s, cmd):
        ctx.emit("step", what="report", n=None)
        mx.notify_parent(ctx, "done")

    @acts.action
    def report_twice(ctx, s, cmd):
        mx.notify_parent(ctx, "done")
        mx.notify_parent(ctx, "done")

    @desk.action
    def decide(ctx, s, cmd):
        if cmd.verdict == "no":
            return ctx.reject("refused")
        if cmd.verdict == "slow":
            return ctx.reject("never") if False else None
        return ctx.reply()

    k._pack = p
    define_machine(k)

    @p.source
    def go(src):
        src.create("desk", key=0)
        for _ in range(cases):
            src.create("case", at=0.0)
    return p


def _run(p, days=30.0, debug=True):
    plan = build_plan(p)
    assert validate(plan) == []
    return simulate(plan, None, RunConfig(days=days, debug=debug))


def _steps(out, pid=None):
    df = out.events["step"].sort("seq")
    if pid is not None:
        df = df.filter(pl.col("partition_id") == pid)
    return df["what"].to_list()


def test_branch_and_timer_race_leaving_cancels_the_other():
    def define(k):
        m = k.machine("pay", initial="authorized")
        m.state("authorized", branch={"captured": (0.7, dist.exp(mean_days=3), "capture"),
                                      "otherwise": (0.3, None, None)},
                timer={"expired": ("7d", "c")})
        m.state("captured", repeat=(dist.exp(mean_days=2), 1.0, "refund"), max_repeats=2,
                then="done")
        m.state("expired", retire=True)
        m.state("done")
    out = _run(_pack(define, cases=200))
    per = out.events["step"].sort("seq").group_by("partition_id", maintain_order=True).agg(
        pl.col("what"))["what"].to_list()
    shapes = {tuple(x) for x in per}
    assert shapes <= {("capture", "refund", "refund"), ("c",), ("capture", "refund"),
                      ("capture",)}
    assert ("c",) in shapes and ("capture", "refund", "refund") in shapes
    expired = sum(x == ["c"] for x in per)
    assert 30 < expired < 120                      # otherwise (30%) + slow captures lose the race
    retired = out.cases.filter(pl.col("kind") == "case")["censored"]
    assert (~retired).sum() == expired


def test_repeat_until_condition_then():
    def define(k):
        m = k.machine("r", initial="loop")
        m.state("loop", repeat=("1h", 1.0, "a"), max_repeats=10, until=cond.attr_ge("n", 3),
                then="out")
        m.state("out", on_enter="b")
    out = _run(_pack(define))
    assert _steps(out) == ["a", "a", "a", "b"]


def test_then_keeps_the_first_part_when_the_second_rejects():
    def define(k):
        m = k.machine("t", initial="s0")
        m.state("s0", timer={"s1": ("1h", Then("a", "nope", fallback="c"))})
        m.state("s1", on_enter="b")
    out = _run(_pack(define))
    assert _steps(out) == ["a", "c", "b"]


def test_a_rejected_action_goes_to_on_reject():
    def define(k):
        m = k.machine("t", initial="s0")
        m.state("s0", timer={"s1": ("1h", "nope")}, on_reject="failed")
        m.state("s1", on_enter="a")
        m.state("failed", on_enter="c")
    assert _steps(_run(_pack(define))) == ["c"]


@pytest.mark.parametrize(("verdict", "want"), [("yes", ["a"]), ("no", ["c"])])
def test_request_ok_and_rejection_branches(verdict, want):
    def define(k):
        m = k.machine("q", initial="ask")
        m.state("ask", request={"granted": Request(("desk", 0), "decide", timeout="30s",
                                                   on_reject="refused",
                                                   payload={"verdict": verdict})})
        m.state("granted", on_enter="a")
        m.state("refused", on_enter="c")
    out = _run(_pack(define))
    assert _steps(out) == want
    t = out.events["step"]["event_time"][0] - pl.datetime(2026, 1, 1, time_zone="UTC")
    assert out.events["step"].select(t.dt.total_seconds()).item() == pytest.approx(1.0)


def test_request_timeout_branch():
    def define(k):
        m = k.machine("q", initial="ask")
        m.state("ask", request={"granted": Request(("desk", 0), "decide", timeout="0.5s",
                                                   on_reject="refused", on_timeout="late",
                                                   payload={"verdict": "yes"})})
        m.state("granted", on_enter="a")
        m.state("refused", on_enter="c")
        m.state("late", on_enter="late_one")
    out = _run(_pack(define))
    assert _steps(out) == ["late_one"]
    assert out.stats.late_replies == 1


def test_spawn_join_duplicates_and_late_children():
    def define(k):
        p = k._pack
        kid = p.owner("kid", state=Case)
        acts = kid.process("acts")

        @acts.action
        def report(ctx, s, cmd):
            ctx.emit("step", what="report", n=None)
            mx.notify_parent(ctx, "done")

        @acts.action
        def report_twice(ctx, s, cmd):                  # a duplicate, then (later) late
            mx.notify_parent(ctx, "done")
            mx.notify_parent(ctx, "done")

        child = kid.machine("kid_life", initial="wait")
        child.state("wait", timer={"said": (dist.uniform("1h", "5h"),
                                            Then("report", "report_twice"))})
        child.state("said", timer={"again": ("20d", "report_twice")})
        child.state("again")
        par = k.machine("parent", initial="start")
        par.state("start", spawn=Spawn("kid", n=3), join={"collected": ("done", "all_spawned")},
                  join_timeout=("10d", "timed_out"), late="count")
        par.state("collected", on_enter="b")
        par.state("timed_out", on_enter="c")
    out = _run(_pack(define))
    steps = _steps(out)
    assert steps.count("report") == 3 and steps[-1] == "b" and "c" not in steps
    rej = out.stats.rejections
    # the first two kids repeat before the join completes (duplicates); the third kid's
    # first message completes it, so its repeats, and everyone's later pair, are late
    assert rej[("case", "mx_child", "duplicate_child_message")] == 4
    assert rej[("case", "mx_child", "late_child_message")] == 2 + 6
    kids = out.cases.filter(pl.col("kind") == "kid")
    assert kids.height == 3 and (kids["depth"] == 1).all()


def test_zero_children_join_fires_at_once():
    def define(k):
        m = k.machine("p", initial="start")
        m.state("start", spawn=Spawn("case", n=0), join={"next": ("done", "all_spawned")},
                join_timeout=("1d", "timeout"))
        m.state("next", on_enter="a")
        m.state("timeout", on_enter="c")
    out = _run(_pack(define))
    assert _steps(out) == ["a"]
    from datetime import UTC, datetime
    assert out.events["step"]["event_time"][0] == datetime(2026, 1, 1, tzinfo=UTC)


def test_validation_of_machines():
    def define(k):
        m = k.machine("bad", initial="nowhere")
        m.state("s", branch={"t": (0.5, None, None)}, join={"x": ("m", 1)},
                request={"y": Request(("desk", 0), "decide", timeout="", on_reject="")},
                timer={"zz": ("1h", "missing_action")})
    errs = validate(build_plan(_pack(define)))
    text_ = "\n".join(errs)
    for frag in ("initial state 'nowhere'", "sum to 1", "join needs join_timeout",
                 "request needs a timeout", "unknown target state 'zz'",
                 "unknown action 'missing_action'"):
        assert frag in text_, frag


def test_machines_are_deterministic_and_debug_clean():
    def define(k):
        m = k.machine("pay", initial="authorized")
        m.state("authorized", branch={"captured": (0.5, dist.exp(mean_days=1), "capture"),
                                      "otherwise": (0.5, None, None)}, timer={"gone": "3d"})
        m.state("captured", repeat=(dist.exp(mean_days=1), 0.5, "refund"), max_repeats=4)
        m.state("gone", retire=True)
    a = _run(_pack(define, cases=50), debug=False)
    b = _run(_pack(define, cases=50), debug=True)
    assert a.events["step"].equals(b.events["step"])
    assert DAY == 86_400.0


def test_config_driven_branch_and_timer():
    @dataclass
    class Cfg:
        p_a: float = 1.0
        wait_days: float = 2.0

    def define(k):
        m = k.machine("c", initial="s0")
        m.state("s0", branch={"s1": ("cfg.p_a", "1h", "a"), "otherwise": (None, None, None)},
                timer={"s2": ("cfg.wait_days", "c")})
        m.state("s1", on_enter="b")
        m.state("s2")
    plan = build_plan(_pack(define))
    assert validate(plan) == []
    out = simulate(plan, Cfg(), RunConfig(days=5))
    assert _steps(out) == ["a", "b"]
    out = simulate(build_plan(_pack(define)), Cfg(p_a=0.0), RunConfig(days=5))
    assert _steps(out) == ["c"]
    t = out.events["step"]["event_time"][0] - out.events["step"]["event_time"][0].replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    assert t.total_seconds() == 2 * 86_400
