"""The event loop: ordering, requests, validate → commit, guards and keyed streams."""

from dataclasses import dataclass, field

import polars as pl
import pytest

from neorisk_simkit.engine import DAY, RunConfig, SimError, simulate
from neorisk_simkit.spec import (
    CONTINUATION,
    Latency,
    Pack,
    PackError,
    build_plan,
    cat,
    i64,
    opt,
    ref,
    validate,
)


@dataclass
class Acct:
    balance: int = 0
    log: list = field(default_factory=list)


@dataclass
class Shop:
    stock: int = 1


@dataclass
class Cfg:
    n: int = 3


def _pack(**kw) -> Pack:
    """Accounts that tick daily, request a unit from a shop shard and log replies."""
    p = Pack("t", config=Cfg)
    p.entity("users", key="user_id", cols={"tier": cat("a", "b")})
    p.event("tick", cols={"user_id": ref("users"), "n": i64()})
    p.event("got", cols={"user_id": ref("users"), "status": cat("ok", "rejected", "timeout"),
                         "reason": opt(cat("sold_out"))})
    p.event("sold", cols={"left": i64(min=0)})
    acct = p.owner("acct", state=Acct)
    shop = p.shard("shop", state=Shop, latency=Latency(kw.get("lat", 0.3), kw.get("lat", 0.3)))
    life = acct.process("life", start="hello")

    @life.action
    def hello(ctx, s, cmd):
        s.uid = ctx.insert("users", tier="a")
        ctx.emit("tick", user_id=s.uid, n=0)
        ctx.after(DAY, "tock", n=1)
        ctx.request(ctx.find("shop", 0), "take", reply="answer", timeout=kw.get("timeout"))

    @life.action
    def tock(ctx, s, cmd):
        ctx.emit("tick", user_id=s.uid, n=cmd.n)
        if cmd.n < 3:
            ctx.after(DAY, "tock", n=cmd.n + 1)

    @life.action
    def answer(ctx, s, cmd):
        ctx.emit("got", user_id=s.uid, status=cmd.status, reason=cmd.reason)

    @shop.action
    def take(ctx, s, cmd):
        if s.stock <= 0:
            return ctx.reject("sold_out")
        s.stock -= 1
        ctx.emit("sold", left=s.stock)
        return ctx.reply()

    @p.source
    def population(src):
        src.create("shop", key=0)
        for i in range(src.cfg.n):
            src.create("acct", at=float(src.rng.uniform(0, 3600)) + i)

    return p


def _run(p=None, **run):
    p = p or _pack()
    return simulate(build_plan(p), Cfg(), RunConfig(**{"days": 10, **run}))


def test_pack_rejects_bad_declarations():
    p = Pack("x")
    p.event("e", cols={"a": i64()})
    with pytest.raises(PackError):
        p.event("e", cols={"b": i64()})
    with pytest.raises(PackError):
        p.event("f", cols={"seq": i64()})
    with pytest.raises(PackError):
        p.event("Bad", cols={})


def test_validate_reports_structural_contradictions():
    p = Pack("x")
    p.event("e", cols={"u": ref("nobody")})
    k = p.shard("s", state=Shop, latency=Latency(0.0))
    k.process("p", start="missing")
    errs = validate(build_plan(p))
    assert any("unknown entity table" in e for e in errs)
    assert any("δ must be > 0" in e for e in errs)
    assert any("start action 'missing'" in e for e in errs)
    assert not validate(build_plan(_pack()))


def test_rows_have_common_columns_and_canonical_order():
    out = _run()
    tick = out.events["tick"]
    assert tick.columns[:7] == ["event_id", "event_type", "event_time", "seq", "partition_id",
                                "cause_id", "action_id"]
    assert tick.height == 3 * 4
    allev = out.all_events()
    assert allev["seq"].is_sorted() and allev["event_time"].is_sorted()
    assert out.entities["users"]["user_id"].to_list() == [1, 2, 3]
    # a timer's rows cite the event of the action that scheduled it
    t = tick.sort("seq")
    first = t.filter(pl.col("n") == 0).row(0, named=True)
    second = t.filter((pl.col("n") == 1) & (pl.col("partition_id") == first["partition_id"]))
    assert second["cause_id"][0] == first["event_id"]


def test_request_reply_rejection_and_latency():
    out = _run()
    got = out.events["got"].sort("seq")
    assert got["status"].to_list().count("ok") == 1
    assert got["status"].to_list().count("rejected") == 2
    assert set(got.filter(pl.col("status") == "rejected")["reason"]) == {"sold_out"}
    sold = out.events["sold"]
    lag = (got.filter(pl.col("status") == "ok")["event_time"][0] - sold["event_time"][0])
    assert lag.total_seconds() == pytest.approx(0.3, abs=1e-5)
    assert out.stats.rejections[("shop", "take", "sold_out")] == 2


def test_timeout_wins_over_a_slow_reply():
    out = _run(_pack(lat=5.0, timeout=1.0))
    assert set(out.events["got"]["status"]) == {"timeout"}
    assert out.stats.late_replies == 3


def test_same_seed_same_rows_and_seed_changes_them():
    a, b, c = _run(), _run(), _run(seed=8)
    assert all(a.events[k].equals(b.events[k]) for k in a.events)
    assert not a.events["tick"]["event_time"].equals(c.events["tick"]["event_time"])


def _pri_pack(credit_priority):
    p = Pack("pri")
    p.event("op", cols={"kind": cat("debit", "credit"), "balance": i64()})
    k = p.owner("acct", state=Acct)
    life = k.process("life", start="go")

    @life.action
    def go(ctx, s, cmd):
        ctx.after(10, "debit")          # pushed first
        ctx.after(10, "credit")         # same time, pushed second

    @life.action
    def debit(ctx, s, cmd):
        s.balance -= 5
        ctx.emit("op", kind="debit", balance=s.balance)

    def credit(ctx, s, cmd):
        s.balance += 5
        ctx.emit("op", kind="credit", balance=s.balance)
    life.action(credit, priority=credit_priority)

    @p.source
    def one(src):
        src.create("acct")
    return p


def test_priority_inversion_runs_the_higher_priority_first():
    plain = simulate(build_plan(_pri_pack(None)), None, RunConfig(days=1))
    assert plain.events["op"].sort("seq")["kind"].to_list() == ["debit", "credit"]
    inv = simulate(build_plan(_pri_pack(CONTINUATION)), None, RunConfig(days=1))
    ops = inv.events["op"].sort("seq")
    assert ops["kind"].to_list() == ["credit", "debit"]
    assert ops["balance"].to_list() == [5, 0]


def _bad_pack(body, *, process_depth=3):
    p = Pack("bad")
    p.event("e", cols={"x": i64()})
    k = p.owner("o", state=Acct)
    life = k.process("life", start="go", max_spawn_depth=process_depth)
    life.action(name="go")(body)

    @p.source
    def one(src):
        src.create("o")
    return p


def test_reject_after_a_write_fails_the_run():
    def go(ctx, s, cmd):
        ctx.emit("e", x=1)
        return ctx.reject("too_late")
    with pytest.raises(SimError, match="after its first write"):
        simulate(build_plan(_bad_pack(go)), None, RunConfig(days=1))


def test_debug_mode_catches_state_changed_by_a_rejected_action():
    def go(ctx, s, cmd):
        s.balance = 99
        return ctx.reject("nope")
    plan = build_plan(_bad_pack(go))
    simulate(plan, None, RunConfig(days=1))                      # not detected without debug
    with pytest.raises(SimError, match="after changing"):
        simulate(build_plan(_bad_pack(go)), None, RunConfig(days=1, debug=True))


def test_exceptions_name_the_action_partition_and_time():
    def go(ctx, s, cmd):
        return 1 / 0
    with pytest.raises(SimError, match=r"o\.go \(process 'life', partition 1, t=0\.000\) "
                                       r"raised ZeroDivisionError"):
        simulate(build_plan(_bad_pack(go)), None, RunConfig(days=1))


def test_runaway_spawn_and_event_guards():
    def spawn(ctx, s, cmd):
        ctx.create("o")
    with pytest.raises(SimError, match="max_spawn_depth 3 of process 'life'"):
        simulate(build_plan(_bad_pack(spawn)), None, RunConfig(days=1))

    def loop(ctx, s, cmd):
        ctx.emit("e", x=1)
        ctx.after(0.001, "go")
    with pytest.raises(SimError, match="max_events=50"):
        simulate(build_plan(_bad_pack(loop)), None, RunConfig(days=1, max_events=50))


def test_late_messages_to_retired_partitions_are_dropped_and_counted():
    def go(ctx, s, cmd):
        ctx.after(5, "go")
        ctx.retire()
    out = simulate(build_plan(_bad_pack(go)), None, RunConfig(days=1))
    assert out.stats.late_messages == 1
    assert out.cases["censored"].to_list() == [False]


def test_emit_schema_checks():
    def unknown(ctx, s, cmd):
        ctx.emit("e", x=1, y=2)
    with pytest.raises(SimError, match="no columns"):
        simulate(build_plan(_bad_pack(unknown)), None, RunConfig(days=1))

    def wrong(ctx, s, cmd):
        ctx.emit("e", x="one")
    with pytest.raises(SimError, match="does not fit i64"):              # at emit, in debug
        simulate(build_plan(_bad_pack(wrong)), None, RunConfig(days=1, debug=True))
    with pytest.raises(SimError, match=r"e\.x: values do not fit"):        # at the end otherwise
        simulate(build_plan(_bad_pack(wrong)), None, RunConfig(days=1))

    def missing(ctx, s, cmd):
        ctx.emit("e")
    with pytest.raises(SimError, match="null values in a required column"):
        simulate(build_plan(_bad_pack(missing)), None, RunConfig(days=1))


def test_amounts_outside_int64_fail_on_export():
    def huge(ctx, s, cmd):
        ctx.emit("e", x=2**70)
    with pytest.raises(SimError, match="out of int64 range"):
        simulate(build_plan(_bad_pack(huge)), None, RunConfig(days=1))


def test_keyed_streams_survive_an_unrelated_source():
    base = _run()
    p = _pack()

    @p.source
    def extra(src):                          # a later source: new partitions, new draws
        for _ in range(5):
            src.create("acct", at=float(src.rng.uniform(0, 7200)))
    more = simulate(build_plan(p), Cfg(), RunConfig(days=10))
    a = base.events["tick"].filter(pl.col("partition_id") <= 4)
    b = more.events["tick"].filter(pl.col("partition_id") <= 4)
    keep = ["partition_id", "event_time", "n"]       # same partitions, same draws
    assert a.select(keep).equals(b.select(keep))


def test_warmup_rows_are_not_exported_and_a_snapshot_is_taken():
    out = _run(warmup_days=1.5)
    t = out.events["tick"]
    assert t.height == 3 * 2 and (t["n"] >= 2).all()
    snap = out.snapshots["acct"]
    assert snap.height == 3 and "balance" in snap.columns
