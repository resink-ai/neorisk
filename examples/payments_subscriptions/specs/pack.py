"""Subscription billing: trials, monthly renewals, dunning and churn, as a state machine.

Each subscriber runs one `subscription` machine. A trial converts after 14 days unless the
subscriber cancels first. Every charge is a request to the processor shard; a decline enters
dunning, which retries 3, 5 and 7 days after the failure before cancelling (involuntary).
Each renewal may be the moment a subscriber leaves (voluntary). Written from the brief with
the public pack API only (examples/AGENTS.md).

Machine branch probabilities and delays are literals, so the trial-cancel (25%) and renewal
churn (4%) rates live here rather than in Config.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from neorisk_simkit.checks import laws
from neorisk_simkit.engine import DAY
from neorisk_simkit.machine import Request, Then
from neorisk_simkit.spec import Latency, Pack, amount, cat, dist, i32, i64, ref

NAME = "payments_subscriptions"
PLANS = ("basic", "standard", "premium")
PRICE = (800, 1300, 2000)
RETRY_DAYS = (3, 5, 7)


@dataclass
class Config:
    subscribers: int = 1500
    plan_mix: tuple[float, float, float] = (0.4, 0.4, 0.2)
    trial_days: float = 14.0
    card_health_alpha: float = 12.0        # Beta(a, 1): most cards are healthy
    retry_recover_p: float = 0.35          # a retry succeeds this often on a sick card


@dataclass
class Subscriber:
    sid: int = 0
    plan: str = "basic"
    price: int = 800
    health: float = 0.95                   # chance a charge on this card goes through
    attempt: int = 0                       # charge attempts in the current cycle
    cycle: int = 0


@dataclass
class Processor:
    pass


def define(p: Pack) -> None:
    p.entity("subscribers", key="subscriber_id", cols={"plan": cat(*PLANS),
                                                       "signup_channel": cat("web", "app")})
    sub = {"subscriber_id": ref("subscribers")}
    p.event("subscription_started", cols={**sub, "plan": cat(*PLANS), "price": amount()})
    p.event("trial_converted", cols=sub)
    p.event("invoice_paid", cols={**sub, "cycle": i32(min=1), "attempt": i32(min=1),
                                  "amount": amount()})
    p.event("charge_failed", cols={**sub, "cycle": i32(min=1), "attempt": i32(min=1),
                                   "amount": amount(), "reason": cat("declined", "timeout")})
    p.event("subscription_cancelled", cols={
        **sub, "reason": cat("trial_cancel", "voluntary", "involuntary"),
        "cycles_paid": i64(min=0)})

    subscriber = p.owner("subscriber", state=Subscriber, latency=Latency(0.05, 0.3))
    processor = p.shard("processor", state=Processor, latency=Latency(0.5, 3.0))
    acts = subscriber.process("billing_actions")

    def charge(ctx, s):
        return {"subscriber": s.sid, "amount": s.price, "health": s.health,
                "retry": s.attempt > 1}

    @acts.action
    def start(ctx, s, cmd):
        ctx.emit("subscription_started", subscriber_id=s.sid, plan=s.plan, price=s.price)

    @acts.action
    def new_cycle(ctx, s, cmd):
        s.cycle, s.attempt = s.cycle + 1, 1

    @acts.action
    def next_attempt(ctx, s, cmd):
        s.attempt += 1

    @acts.action
    def convert(ctx, s, cmd):
        ctx.emit("trial_converted", subscriber_id=s.sid)

    @acts.action
    def paid(ctx, s, cmd):
        ctx.emit("invoice_paid", subscriber_id=s.sid, cycle=s.cycle, attempt=s.attempt,
                 amount=s.price)

    @acts.action
    def failed(ctx, s, cmd):
        ctx.emit("charge_failed", subscriber_id=s.sid, cycle=s.cycle, attempt=s.attempt,
                 amount=s.price, reason="declined")

    def cancel(reason):
        def go(ctx, s, cmd):
            ctx.emit("subscription_cancelled", subscriber_id=s.sid, reason=reason,
                     cycles_paid=s.cycle - (0 if reason == "voluntary" else 1)
                     if s.cycle else 0)
        return go
    for r in ("trial_cancel", "voluntary", "involuntary"):
        acts.action(cancel(r), name=f"cancel_{r}")

    @processor.action
    def charge_card(ctx, s, cmd):
        p_ok = cmd.health if not cmd.retry else max(cmd.health, ctx.cfg.retry_recover_p)
        if ctx.rng.random() >= p_ok:
            return ctx.reject("declined")
        return ctx.reply()

    # --- the lifecycle, as a machine (no handwritten control flow) -----------------------
    m = subscriber.machine("subscription", initial="trial")

    def ask(ok: str, no: str) -> dict:
        return {ok: Request(("processor", "main"), "charge_card", timeout="1h",
                            on_reject=no, payload=charge)}

    m.state("trial", on_enter="start",
            branch={"trial_cancelled": (0.25, dist.uniform("1d", "13d"), None),
                    "otherwise": (0.75, None, None)},
            timer={"charging": ("14d", "convert")})
    m.state("trial_cancelled", on_enter="cancel_trial_cancel", retire=True)
    m.state("charging", on_enter="new_cycle", request=ask("active", "dunning_1"))
    m.state("active", on_enter="paid",
            branch={"churned": (0.04, dist.uniform("20d", "29d"), None),
                    "otherwise": (0.96, None, None)},
            timer={"charging": "30d"})
    m.state("churned", on_enter="cancel_voluntary", retire=True)
    for i, days in enumerate(RETRY_DAYS, start=1):
        nxt = f"dunning_{i + 1}" if i < len(RETRY_DAYS) else "lapsed"
        m.state(f"dunning_{i}", on_enter="failed",
                timer={f"retry_{i}": (f"{days}d", "next_attempt")})
        m.state(f"retry_{i}", request=ask("active", nxt))
    m.state("lapsed", on_enter=Then("failed", "cancel_involuntary"), retire=True)

    # --- laws ---------------------------------------------------------------------------
    p.check("lifecycle", laws.lifecycle("subscriber_id", {
        None: {"subscription_started"},
        "subscription_started": {"trial_converted", "subscription_cancelled"},
        "trial_converted": {"invoice_paid", "charge_failed"},
        "invoice_paid": {"invoice_paid", "subscription_cancelled", "charge_failed"},
        "charge_failed": {"charge_failed", "invoice_paid", "subscription_cancelled"}}))
    p.check("one_payment_per_cycle", laws.unique("invoice_paid", ["subscriber_id", "cycle"]))
    p.check("involuntary_after_all_retries", _involuntary)
    p.check("paid_cycles_are_monthly", _monthly)

    @p.source
    def subscribers(src):
        cfg, rng = src.cfg, src.rng
        for _ in range(cfg.subscribers):
            t = rng.uniform(0, 0.5 * src.days) * DAY
            k = int(rng.choice(3, p=cfg.plan_mix))
            sid = src.insert("subscribers", at=t, plan=PLANS[k],
                             signup_channel="web" if rng.random() < 0.6 else "app")
            src.create("subscriber", at=t, sid=sid, plan=PLANS[k], price=PRICE[k],
                       health=float(rng.beta(cfg.card_health_alpha, 1.0)))
        src.create("processor", key="main")


CITE = ("partition_id", "seq", "action_id")


def _involuntary(d):
    """An involuntary cancel follows a failed first charge and every retry of its cycle."""
    c = d.ev("subscription_cancelled").filter(pl.col("reason") == "involuntary")
    f = d.ev("charge_failed").group_by("subscriber_id").agg(pl.col("attempt").max())
    j = c.join(f, on="subscriber_id", how="left")
    bad = j.filter(pl.col("attempt").fill_null(0) < len(RETRY_DAYS) + 1)
    return c.height, bad.select(*CITE, pl.lit("cancelled before all retries").alias("detail"))


def _monthly(d):
    """Consecutive paid cycles of a subscriber are about 30 days apart (dunning adds days)."""
    p_ = d.ev("invoice_paid").sort("seq").with_columns(
        gap=(pl.col("event_time") - pl.col("event_time").shift(1).over("subscriber_id"))
        .dt.total_days())
    bad = p_.filter(pl.col("gap").is_not_null()
                    & ((pl.col("gap") < 29) | (pl.col("gap") > 30 + sum(RETRY_DAYS) + 1)))
    return p_.height, bad.select(*CITE, pl.lit("renewal gap out of range").alias("detail"))
