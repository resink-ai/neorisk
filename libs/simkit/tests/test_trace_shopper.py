"""§07 trace: a recurring shopper buying two SKUs.

10:00:00.0  U holds 80 of its spending limit, sends reserve(A) and reserve(B); join of 2.
            A grants and holds one unit (TTL 10 min); B declines (out of stock). Both decision
            rows carry 10:00:00.0.
10:00:00.3  A's reply arrives; U keeps waiting for B.
10:00:00.4  B's reply arrives: U releases its hold, sends release(A), emits checkout_failed.
10:02:10.0  U picks substitute C, holds 40, sends reserve(C).
10:02:10.4  C granted: U commits its hold, sends commit(C), creates payment P, emits
            checkout_succeeded; P records itself at the same instant.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

import polars as pl
import pytest

from neorisk_simkit.engine import RunConfig, simulate
from neorisk_simkit.spec import Latency, Pack, amount, build_plan, cat, i64, validate
from neorisk_simkit.std import holds, reservations

T0 = 10 * 3600.0
PRICE = {1: 40, 2: 40, 3: 40}                     # items A, B, C


@dataclass
class Shopper:
    limit: int = 200
    spent: int = 0
    held: holds.Holds = field(default_factory=holds.Holds)
    hold: int | None = None
    waiting: dict[int, str | None] = field(default_factory=dict)   # item -> status
    granted: dict[int, int] = field(default_factory=dict)          # item -> reservation id


@dataclass
class Inventory(reservations.Stock):
    pass


@dataclass
class Payment:
    amount: int = 0


def trace_pack() -> Pack:
    p = Pack("trace")
    holds.declare(p)
    p.event("checkout_failed", cols={"reason": cat("out_of_stock", "timeout")})
    p.event("checkout_succeeded", cols={"amount": amount(), "payment_partition": i64()})
    p.event("payment_created", cols={"amount": amount()})
    u = p.owner("shopper", state=Shopper)
    inv = p.shard("inventory", state=Inventory, latency=Latency(0.2, 0.5))
    reservations.install(p, inv, ttl=600)
    pay = p.owner("payment", state=Payment)
    journey = u.process("journey", start="begin")

    @journey.action
    def begin(ctx, s, cmd):
        ctx.at(T0, "checkout", items=[1, 2])

    @journey.action
    def checkout(ctx, s, cmd):
        total = sum(PRICE[i] for i in cmd.items)
        hid = holds.place(ctx, s.held, total, free=s.limit - s.spent, purpose="checkout")
        if hid is None:
            return ctx.reject("over_limit")
        s.hold, s.waiting, s.granted = hid, dict.fromkeys(cmd.items), {}
        for i in cmd.items:                      # A answers in 0.3 s, B and C in 0.4 s
            ctx.request(ctx.find("inventory", i), "reserve", reply="reserved", item=i, qty=1,
                        timeout=30, latency=0.3 if i == 1 else 0.4)

    @journey.action
    def reserved(ctx, s, cmd):
        item = cmd.payload.get("item") or next(i for i, v in s.waiting.items() if v is None)
        s.waiting[item] = cmd.status
        if cmd.ok:
            s.granted[item] = cmd.reservation
        if any(v is None for v in s.waiting.values()):
            return ctx.commit()                  # join: wait for every reply
        if all(v == "ok" for v in s.waiting.values()):
            amt = holds.commit(ctx, s.held, s.hold)
            s.spent += amt
            for i, rid in s.granted.items():
                ctx.send(ctx.find("inventory", i), "commit_reservation", reservation=rid)
            pid = ctx.create("payment", amount=amt)
            ctx.emit("checkout_succeeded", amount=amt, payment_partition=pid)
            return ctx.commit()
        holds.release(ctx, s.held, s.hold, "out_of_stock")
        for i, rid in s.granted.items():
            ctx.send(ctx.find("inventory", i), "release_reservation", reservation=rid)
        ctx.emit("checkout_failed", reason="out_of_stock")
        ctx.at(T0 + 130, "checkout", items=[3])  # back to browsing; substitute C at 10:02:10

    @pay.action
    def created(ctx, s, cmd):
        ctx.emit("payment_created", amount=s.amount)
    pay.processes["payment"].start = "created"

    @p.source
    def world(src):
        for item, units in ((1, 5), (2, 0), (3, 5)):
            src.create("inventory", key=item, units={item: units})
        src.create("shopper")
    return p


@pytest.fixture(scope="module")
def out():
    plan = build_plan(trace_pack())
    assert validate(plan) == []
    return simulate(plan, None, RunConfig(days=1, debug=True,
                                          start=datetime(2026, 3, 1, tzinfo=UTC)))


def test_the_trace_in_canonical_order(out):
    rows = (out.all_events(["seq", "event_time", "event_type", "partition_id"])
            .with_columns(t=(pl.col("event_time") - pl.datetime(2026, 3, 1, 10, time_zone="UTC"))
                          .dt.total_microseconds() / 1e6))
    kinds = dict(zip(out.cases["partition_id"], out.cases["kind"], strict=True))
    got = [(round(r["t"], 1), kinds[r["partition_id"]], r["event_type"])
           for r in rows.iter_rows(named=True) if r["event_type"] != "reservation_released"]
    assert got[:-1] == [
        (0.0, "shopper", "hold_placed"),
        (0.0, "inventory", "reservation_granted"),      # A
        (0.0, "inventory", "reservation_declined"),     # B
        (0.4, "shopper", "hold_released"),
        (0.4, "shopper", "checkout_failed"),
        (130.0, "shopper", "hold_placed"),
        (130.0, "inventory", "reservation_granted"),    # C
        (130.4, "shopper", "hold_committed"),
        (130.4, "shopper", "checkout_succeeded"),
        (130.4, "payment", "payment_created"),
    ]
    assert got[-1][1:] == ("inventory", "reservation_committed")
    commit = rows.filter(pl.col("event_type") == "reservation_committed")["t"][0]
    assert 130.4 + 0.2 <= commit <= 130.4 + 0.5          # delivered after ≥ δ


def test_a_is_released_by_the_owner_and_never_expires(out):
    rel = out.events["reservation_released"]
    assert rel["reason"].to_list() == ["released"]
    t = (rel["event_time"][0] - datetime(2026, 3, 1, 10, tzinfo=UTC)).total_seconds()
    assert 0.4 + 0.2 <= t <= 0.4 + 0.5


def test_no_mutable_state_crossed_and_everything_resolved(out):
    placed = set(out.events["hold_placed"]["hold_id"])
    resolved = set(out.events["hold_committed"]["hold_id"]) | set(
        out.events["hold_released"]["hold_id"])
    assert placed == resolved
    granted = set(out.events["reservation_granted"]["reservation_id"])
    assert granted == set(out.events["reservation_committed"]["reservation_id"]) | set(
        out.events["reservation_released"]["reservation_id"])
    assert out.stats.rejections[("inventory", "reserve", "out_of_stock")] == 1
    pay = out.events["checkout_succeeded"]
    assert pay["amount"].to_list() == [40]
