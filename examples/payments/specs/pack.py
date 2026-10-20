"""Card payments: authorization, capture, refunds, disputes and merchant settlement.

Customers buy from merchants at a steady rate. Each purchase first holds the amount on the
customer's own credit line, then creates a payment owner that asks the issuer (a shard) to
authorize it. An authorized payment is captured after about an hour (a capture can be retried
with the same idempotency key; the retry replays the first result), or expires after 7 days.
Captured payments may be partially refunded up to three times; each refund holds the
remaining refundable amount, asks the processor, then commits or releases the hold. A dispute
is a child process of the payment: refunds are refused while it is open, and a lost dispute
charges the payment back. Merchant account shards accumulate captures, refunds, chargebacks
and fees and post a settlement every day. Customers pay their statement every 30 days.

Fraud: a small share of payments is fraudulent; most of them are disputed (reason "fraud")
weeks later. The label is decided at authorization but becomes available only at the dispute.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import polars as pl

from neorisk_simkit.checks import laws
from neorisk_simkit.engine import DAY, HOUR
from neorisk_simkit.spec import Latency, Pack, amount, cat, i64, opt, ref
from neorisk_simkit.std import holds

NAME = "payments"
SCHEMA_VERSION = 1

SEGMENTS = ("consumer", "small_business", "premium")
COUNTRIES = ("US", "CA", "GB", "DE", "FR", "BR", "IN")
MCCS = ("grocery", "travel", "digital_goods", "electronics", "restaurants", "fuel")
BRANDS = ("visa", "mastercard", "amex")
DECLINES = ("over_limit", "risk")
DISPUTE_REASONS = ("fraud", "not_received", "not_as_described")


@dataclass
class Config:
    customers: int = 800
    merchants: int = 120
    merchant_zipf: float = 1.0
    purchases_per_day: float = 0.3
    amount_median_cents: int = 4500
    amount_sigma: float = 0.9
    limit_median_cents: int = 250_000
    risk_decline_p: float = 0.02
    capture_p: float = 0.93
    capture_median_s: float = 3600.0
    capture_retry_p: float = 0.05     # the merchant retries a capture with the same key
    auth_ttl_days: float = 7.0
    refund_p: float = 0.04            # per refund opportunity, up to max_refunds
    refund_mean_days: float = 9.0
    max_refunds: int = 3
    refund_fail_p: float = 0.01
    dispute_p: float = 0.004          # non-fraud payments
    fraud_p: float = 0.005
    fraud_dispute_p: float = 0.8
    dispute_mean_days: float = 21.0
    resolve_mean_days: float = 30.0
    lose_p: float = 0.4               # non-fraud disputes lost by the merchant
    fee_bps: int = 290
    fee_fixed_cents: int = 30
    statement_days: float = 30.0


@dataclass
class Customer:
    cid: int = 0
    card: int = 0
    limit: int = 0
    balance: int = 0                  # committed and not yet paid
    credit: holds.Holds = field(default_factory=holds.Holds)


@dataclass
class Payment:
    pid: int = 0
    customer: int = 0                 # customer id ...
    customer_pid: int = 0             # ... and partition
    merchant: int = 0
    merchant_pid: int = 0
    card: int = 0
    amount: int = 0
    hold: int = 0                     # the customer's credit hold
    fraud: bool = False
    status: str = "new"               # new | authorized | captured | expired | declined
    key: int | None = None            # idempotency key of the first capture
    captured: int = 0
    refunded: int = 0
    refunds: int = 0
    refund_holds: holds.Holds = field(default_factory=holds.Holds)
    dispute_open: bool = False


@dataclass
class MerchantAccount:
    mid: int = 0
    gross: int = 0
    refunds: int = 0
    chargebacks: int = 0
    fees: int = 0


@dataclass
class Desk:                           # the issuer and the refund processor hold no state
    pass


def define(p: Pack) -> None:
    p.entity("customers", key="customer_id", cols={
        "segment": cat(*SEGMENTS), "country": cat(*COUNTRIES), "credit_limit": amount()})
    p.entity("cards", key="card_id", cols={"customer_id": ref("customers"),
                                           "brand": cat(*BRANDS)})
    p.entity("merchants", key="merchant_id", cols={"mcc": cat(*MCCS), "country": cat(*COUNTRIES)})
    p.entity("payments", key="payment_id", cols={
        "customer_id": ref("customers"), "merchant_id": ref("merchants"),
        "card_id": ref("cards"), "amount": amount()})

    pay_cols = {"payment_id": ref("payments"), "customer_id": ref("customers"),
                "merchant_id": ref("merchants")}
    holds.declare(p, cols={"customer_id": ref("customers"),
                           "payment_id": opt(ref("payments"))})
    p.event("credit_line_opened", cols={"customer_id": ref("customers"), "limit": amount()})
    p.event("statement_paid", cols={"customer_id": ref("customers"), "amount": amount()})
    p.event("payment_declined", doc="Refused before or at authorization", cols={
        "payment_id": opt(ref("payments")), "customer_id": ref("customers"),
        "merchant_id": ref("merchants"), "amount": amount(), "reason": cat(*DECLINES)})
    p.event("payment_authorized", cols={**pay_cols, "card_id": ref("cards"),
                                        "amount": amount()})
    p.event("payment_captured", cols={**pay_cols, "amount": amount(),
                                      "idempotency_key": i64()})
    p.event("capture_replayed", doc="A retried capture key returns the first result",
            cols={**pay_cols, "idempotency_key": i64()})
    p.event("payment_expired", cols={**pay_cols, "amount": amount()})
    p.event("refund_issued", cols={**pay_cols, "amount": amount()})
    p.event("refund_failed", cols={**pay_cols, "amount": amount()})
    p.event("refund_refused", cols={**pay_cols,
                                    "reason": cat("dispute_open", "nothing_refundable")})
    p.event("dispute_opened", cols={**pay_cols, "reason": cat(*DISPUTE_REASONS)})
    p.event("dispute_resolved", cols={**pay_cols, "outcome": cat("won", "lost"),
                                      "chargeback": amount()})
    p.event("settlement_posted", doc="A merchant's daily payout", cols={
        "merchant_id": ref("merchants"), "gross": amount(), "refunds": amount(),
        "chargebacks": amount(), "fees": amount(), "net": amount()})

    customer = p.owner("customer", state=Customer, latency=Latency(0.05, 0.3))
    payment = p.owner("payment", state=Payment, latency=Latency(0.05, 0.3))
    issuer = p.shard("issuer", state=Desk, latency=Latency(0.15, 0.6), doc="Authorizations")
    processor = p.shard("processor", state=Desk, latency=Latency(0.3, 2.0), doc="Refunds")
    merchant = p.shard("merchant_account", state=MerchantAccount, latency=Latency(0.05, 0.5))

    # --- customers ----------------------------------------------------------------------
    wallet = customer.process("wallet", start="open_line")

    @wallet.action
    def open_line(ctx, s, cmd):
        ctx.emit("credit_line_opened", customer_id=s.cid, limit=s.limit)
        ctx.after(ctx.rng.exponential(DAY / ctx.cfg.purchases_per_day), "purchase")
        ctx.after(ctx.cfg.statement_days * DAY, "pay_statement")

    @wallet.action
    def purchase(ctx, s, cmd):
        cfg, rng, m = ctx.cfg, ctx.rng, ctx.shared.merchants
        ctx.after(rng.exponential(DAY / cfg.purchases_per_day), "purchase")
        k = int(np.searchsorted(m.cdf, rng.random(), side="right"))
        mid = int(m.ids[k])
        amt = int(np.exp(rng.normal(np.log(cfg.amount_median_cents), cfg.amount_sigma))) + 50
        hid = holds.place(ctx, s.credit, amt, free=s.limit - s.balance, purpose="purchase",
                          customer_id=s.cid, payment_id=None)
        if hid is None:
            ctx.emit("payment_declined", payment_id=None, customer_id=s.cid, merchant_id=mid,
                     amount=amt, reason="over_limit")
            return ctx.commit()
        ctx.create("payment", customer=s.cid, customer_pid=ctx.self_id, merchant=mid,
                   merchant_pid=ctx.find("merchant_account", mid), card=s.card, amount=amt,
                   hold=hid, fraud=bool(rng.random() < cfg.fraud_p))

    @wallet.action
    def auth_result(ctx, s, cmd):
        if cmd.approved:
            s.balance += holds.commit(ctx, s.credit, cmd.hold, customer_id=s.cid,
                                      payment_id=cmd.payment)
        else:
            holds.release(ctx, s.credit, cmd.hold, cmd.why, customer_id=s.cid,
                          payment_id=cmd.payment)

    @wallet.action
    def credited(ctx, s, cmd):
        s.balance -= cmd.amount           # expiry, refund or chargeback; rows already exist

    @wallet.action
    def pay_statement(ctx, s, cmd):
        if s.balance > 0:
            ctx.emit("statement_paid", customer_id=s.cid, amount=s.balance)
            s.balance = 0
        ctx.after(ctx.cfg.statement_days * DAY, "pay_statement")

    # --- payments -----------------------------------------------------------------------
    life = payment.process("payment_life", start="authorize")
    refunding = payment.process("refunds")
    dispute = payment.process("dispute")

    def ids(s):
        return {"payment_id": s.pid, "customer_id": s.customer, "merchant_id": s.merchant}

    @life.action
    def authorize(ctx, s, cmd):
        s.pid = ctx.insert("payments", customer_id=s.customer, merchant_id=s.merchant,
                           card_id=s.card, amount=s.amount)
        ctx.request(ctx.find("issuer", "main"), "decide", reply="authorized", fraud=s.fraud,
                    amount=s.amount, timeout=30.0)

    @life.action
    def authorized(ctx, s, cmd):
        cfg, rng = ctx.cfg, ctx.rng
        tell = {"hold": s.hold, "payment": s.pid}
        if not cmd.ok:
            s.status = "declined"
            ctx.emit("payment_declined", **ids(s), amount=s.amount, reason="risk")
            ctx.send(s.customer_pid, "auth_result", approved=False, why="risk", **tell)
            ctx.retire()
            return ctx.commit()
        s.status = "authorized"
        ctx.emit("payment_authorized", **ids(s), card_id=s.card, amount=s.amount)
        ctx.send(s.customer_pid, "auth_result", approved=True, why=None, **tell)
        if s.fraud:
            if rng.random() < cfg.fraud_dispute_p:
                delay = rng.gamma(4.0, cfg.dispute_mean_days / 4.0) * DAY
                ctx.label(s.pid, "fraud", table="payments", available_at=ctx.now + delay)
                ctx.after(delay, "open_dispute", cause="fraud")
            else:
                ctx.label(s.pid, "fraud", table="payments",
                          available_at=ctx.now + 120 * DAY)        # never reported
        elif rng.random() < cfg.dispute_p:
            ctx.after(rng.gamma(4.0, cfg.dispute_mean_days / 4.0) * DAY, "open_dispute",
                      cause=DISPUTE_REASONS[1 + rng.integers(2)])
        if rng.random() < cfg.capture_p:
            key = ctx.new_id("idempotency_key")
            delay = rng.lognormal(np.log(cfg.capture_median_s), 1.0)
            ctx.after(delay, "capture", key=key)
            if rng.random() < cfg.capture_retry_p:
                ctx.after(delay + rng.uniform(1, 120), "capture", key=key)
        ctx.after(cfg.auth_ttl_days * DAY, "expire")

    @life.action
    def capture(ctx, s, cmd):
        if s.status == "captured" and cmd.key == s.key:
            ctx.emit("capture_replayed", **ids(s), idempotency_key=cmd.key)
            return ctx.commit()
        if s.status != "authorized":
            return ctx.reject(f"capture_when_{s.status}")
        s.status, s.key, s.captured = "captured", cmd.key, s.amount
        ctx.emit("payment_captured", **ids(s), amount=s.amount, idempotency_key=cmd.key)
        fee = s.amount * ctx.cfg.fee_bps // 10_000 + ctx.cfg.fee_fixed_cents
        ctx.send(s.merchant_pid, "accrue", gross=s.amount, fee=fee)
        ctx.call("schedule_refund")

    @life.action
    def expire(ctx, s, cmd):
        if s.status != "authorized":
            return ctx.commit()                          # captured first: the race is lost
        s.status = "expired"
        ctx.emit("payment_expired", **ids(s), amount=s.amount)
        ctx.send(s.customer_pid, "credited", amount=s.amount)
        ctx.retire()

    @refunding.action
    def schedule_refund(ctx, s, cmd):
        cfg, rng = ctx.cfg, ctx.rng
        if s.refunds < cfg.max_refunds and rng.random() < cfg.refund_p * (cfg.max_refunds
                                                                          - s.refunds):
            ctx.after(rng.exponential(cfg.refund_mean_days * DAY), "refund")

    @refunding.action
    def refund(ctx, s, cmd):
        s.refunds += 1
        if s.dispute_open:
            ctx.emit("refund_refused", **ids(s), reason="dispute_open")
            return ctx.call("schedule_refund")
        left = s.captured - s.refunded
        amt = min(left, int(ctx.rng.lognormal(np.log(2500), 0.8)) + 1)
        hid = holds.place(ctx, s.refund_holds, amt, free=left, purpose="refund",
                          customer_id=s.customer, payment_id=s.pid)
        if hid is None:
            ctx.emit("refund_refused", **ids(s), reason="nothing_refundable")
            return ctx.commit()
        ctx.request(ctx.find("processor", "main"), "process_refund", reply="refund_done",
                    hold=hid, amount=amt, timeout=HOUR)

    @refunding.action
    def refund_done(ctx, s, cmd):
        hid = next(iter(s.refund_holds.open))
        amt = s.refund_holds.open[hid]
        if cmd.ok:
            holds.commit(ctx, s.refund_holds, hid, customer_id=s.customer, payment_id=s.pid)
            s.refunded += amt
            ctx.emit("refund_issued", **ids(s), amount=amt)
            ctx.send(s.customer_pid, "credited", amount=amt)
            ctx.send(s.merchant_pid, "debit", refunds=amt, chargebacks=0)
        else:
            holds.release(ctx, s.refund_holds, hid, cmd.status, customer_id=s.customer,
                          payment_id=s.pid)
            ctx.emit("refund_failed", **ids(s), amount=amt)
        ctx.call("schedule_refund")

    @dispute.action
    def open_dispute(ctx, s, cmd):
        if s.status != "captured" or s.refunded >= s.captured:
            return ctx.reject("nothing_to_dispute")
        s.dispute_open = True
        ctx.emit("dispute_opened", **ids(s), reason=cmd.cause)
        ctx.after(ctx.rng.gamma(3.0, ctx.cfg.resolve_mean_days / 3.0) * DAY, "resolve_dispute",
                  cause=cmd.cause)

    @dispute.action
    def resolve_dispute(ctx, s, cmd):
        lose = 0.9 if cmd.cause == "fraud" else ctx.cfg.lose_p
        s.dispute_open = False
        if ctx.rng.random() < lose:
            back = s.captured - s.refunded
            s.refunded = s.captured
            ctx.emit("dispute_resolved", **ids(s), outcome="lost", chargeback=back)
            ctx.send(s.customer_pid, "credited", amount=back)
            ctx.send(s.merchant_pid, "debit", refunds=0, chargebacks=back)
        else:
            ctx.emit("dispute_resolved", **ids(s), outcome="won", chargeback=0)

    # --- shards -------------------------------------------------------------------------
    @issuer.action
    def decide(ctx, s, cmd):
        risk = ctx.cfg.risk_decline_p * (6.0 if cmd.fraud else 1.0)
        if ctx.rng.random() < risk:
            return ctx.reject("risk")
        return ctx.reply()

    @processor.action
    def process_refund(ctx, s, cmd):
        if ctx.rng.random() < ctx.cfg.refund_fail_p:
            return ctx.reject("processor_error")
        return ctx.reply()

    books = merchant.process("books", start="open_books")

    @books.action
    def open_books(ctx, s, cmd):
        ctx.after(DAY, "settle")

    @books.action
    def accrue(ctx, s, cmd):
        s.gross += cmd.gross
        s.fees += cmd.fee

    @books.action
    def debit(ctx, s, cmd):
        s.refunds += cmd.refunds
        s.chargebacks += cmd.chargebacks

    @books.action
    def settle(ctx, s, cmd):
        if s.gross or s.refunds or s.chargebacks:
            ctx.emit("settlement_posted", merchant_id=s.mid, gross=s.gross, refunds=s.refunds,
                     chargebacks=s.chargebacks, fees=s.fees,
                     net=s.gross - s.refunds - s.chargebacks - s.fees)
            s.gross = s.refunds = s.chargebacks = s.fees = 0
        ctx.after(DAY, "settle")

    # --- laws ---------------------------------------------------------------------------
    p.check("payment_lifecycle", laws.lifecycle("payment_id", {
        None: {"payment_authorized", "payment_declined"},
        "payment_authorized": {"payment_captured", "payment_expired"}}))
    p.check("one_capture_per_payment", laws.unique("payment_captured", ["payment_id"]))
    p.check("refunds_le_captured", laws.sum_le(("refund_issued", "amount"),
                                               ("payment_captured", "amount"), "payment_id"))
    p.check("no_refund_while_disputed", laws.not_while_open(
        "refund_issued", "dispute_opened", ["dispute_resolved"], "payment_id"))
    p.check("dispute_lifecycle", laws.lifecycle("payment_id", {
        None: {"dispute_opened"}, "dispute_opened": {"dispute_resolved"}}))
    p.check("holds_resolved", laws.holds_resolved())
    for_purchase = pl.col("purpose") == "purchase"
    p.check("credit_limit_respected", laws.running_nonneg(
        "customer_id",
        plus=[("credit_line_opened", "limit"), ("hold_released", "amount", for_purchase),
              ("statement_paid", "amount"), ("payment_expired", "amount"),
              ("refund_issued", "amount"), ("dispute_resolved", "chargeback")],
        minus=[("hold_placed", "amount", for_purchase)], what="available credit"), group="cross")
    p.check("settled_le_captured", laws.sum_le(
        ("settlement_posted", "gross"), ("payment_captured", "amount"), "merchant_id"),
        group="cross")
    p.check("settlement_arithmetic", lambda d: (
        d.ev("settlement_posted").height,
        d.ev("settlement_posted").filter(
            pl.col("net") != pl.col("gross") - pl.col("refunds") - pl.col("chargebacks")
            - pl.col("fees")).select("partition_id", "seq", "action_id")))

    @p.source
    def world(src):
        cfg, rng = src.cfg, src.rng
        mids = []
        for _ in range(cfg.merchants):
            mid = src.insert("merchants", mcc=MCCS[rng.integers(len(MCCS))],
                             country=COUNTRIES[rng.integers(len(COUNTRIES))])
            src.create("merchant_account", key=mid, mid=mid)
            mids.append(mid)
        w = 1.0 / np.arange(1, cfg.merchants + 1) ** cfg.merchant_zipf
        src.share("merchants", ids=np.array(mids), cdf=np.cumsum(w) / w.sum())
        src.create("issuer", key="main")
        src.create("processor", key="main")
        for _ in range(cfg.customers):
            t = rng.uniform(0, 0.2 * src.days) * DAY
            limit = int(np.exp(rng.normal(np.log(cfg.limit_median_cents), 0.5)))
            cid = src.insert("customers", at=t, segment=SEGMENTS[rng.integers(len(SEGMENTS))],
                             country=COUNTRIES[rng.integers(len(COUNTRIES))], credit_limit=limit)
            card = src.insert("cards", at=t, customer_id=cid,
                              brand=BRANDS[rng.integers(len(BRANDS))])
            src.create("customer", at=t, cid=cid, card=card, limit=limit)
