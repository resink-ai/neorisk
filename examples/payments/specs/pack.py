"""Card payments pack (acquirer / PSP view).

Partitions
    owner  cardholder     one cardholder: purchase behavior; never exported (we can't see people)
    owner  payment        one payment: auth, 3DS, capture, settlement, refunds, dispute (child)
    shard  merchant_risk  one merchant group: velocity counters and daily refund headroom

Boundaries (immutable request/response, latency >= delta)
    cardholder -> payment        creation message (a purchase creates the payment owner)
    payment -> merchant_risk     authorize: approve / decline / challenge        delta 80 ms
    payment -> merchant_risk     refund_check: approved / declined (owner holds) delta 80 ms
    payment -> cardholder        none in the base; overlays report to the creator next step or later

Accumulated, never read by a decision
    settlement  per (merchant, batch date) totals      ledger  double-entry postings -> postings/
"""

from dataclasses import dataclass, field

from neorisk_simkit.spec import Pack, dist, law, std
from neorisk_simkit.spec.types import amount, boolean, cat, f64, i16, i32, opt, ref, ts

from . import kernels as k

PACK = "payments"
SCHEMA_VERSION = 1

# MCC code -> (label, median ticket in cents, sigma, online share, refund probability, risk base)
MCC = {
    "5411": ("grocery",          4_200, 0.8, 0.15, 0.020,  5),
    "5812": ("restaurants",      2_800, 0.7, 0.10, 0.010,  5),
    "5541": ("fuel",             4_500, 0.5, 0.02, 0.005,  8),
    "5651": ("apparel",          6_500, 0.8, 0.70, 0.090, 10),
    "5732": ("electronics",     18_000, 1.1, 0.65, 0.050, 20),
    "5815": ("digital_goods",    1_200, 0.9, 0.98, 0.030, 15),
    "5968": ("subscriptions",    1_500, 0.6, 0.95, 0.040, 12),
    "4722": ("travel",          42_000, 0.9, 0.85, 0.080, 18),
    "7011": ("hotels",          30_000, 0.8, 0.60, 0.060, 12),
    "5399": ("general_merch",    5_500, 1.0, 0.75, 0.060, 10),
    "8398": ("charities",        3_000, 1.0, 0.90, 0.010, 10),
    "5947": ("gift_cards",       4_000, 0.9, 0.60, 0.030, 18),
}
MCCS = tuple(MCC)
COUNTRIES = ("US", "GB", "DE", "FR", "CA", "BR", "IN", "other")
SIZES = ("small", "mid", "large", "enterprise")
BRANDS = ("visa", "mastercard", "amex", "discover")
FUNDING = ("credit", "debit", "prepaid")
CARD_STATUS = ("active", "closed", "expired")
CHANNELS = ("ecom", "pos", "moto")
DECLINE_CODES = ("risk_decline", "velocity", "authentication_failed", "authentication_abandoned",
                 "insufficient_funds", "do_not_honor", "suspected_fraud", "limit_exceeded",
                 "invalid_card", "expired_card")
DISPUTE_REASONS = ("fraud", "not_received", "not_as_described", "duplicate",
                   "credit_not_processed", "subscription_canceled")
PAYMENT_STATUS = ("requested", "challenged", "authorized", "declined", "voided", "expired",
                  "captured", "settled")
RESULTS = ("in_progress", "approved", "declined", "succeeded", "rejected")


# --------------------------------------------------------------------------- config
@dataclass(frozen=True)
class Purchases:
    """Cardholder behavior; consumed by kernels.cardholder_purchases."""
    first_purchase: dist.Dist = dist.exp(mean_days=4)       # stagger after activation / start
    home_country_p: float = 0.93
    min_amount: int = 100                                    # cents
    max_amount: int = 1_000_000
    hour_profile: tuple = (1, 1, 1, 1, 1, 2, 3, 5, 6, 7, 8, 9,      # local hour weights
                           10, 9, 8, 8, 8, 9, 10, 10, 9, 7, 4, 2)


@dataclass(frozen=True)
class Auth:
    """Authorization, 3DS and idempotency; consumed by kernels.authorize_payment."""
    issuer_latency: dist.Dist = dist.shifted_lognormal(min_ms=150, median_ms=550, max_ms=8_000)
    issuer_decline_p: float = 0.075
    prepaid_decline_mult: float = 1.8
    authenticated_decline_mult: float = 0.6                  # 3DS liability shift: fewer declines
    issuer_decline_mix: tuple = (0.48, 0.30, 0.12, 0.10)     # insufficient, dnh, fraud, limit
    challenge_time: dist.Dist = dist.lognormal(median_s=45, sigma=0.7, max_s=600)
    three_ds_outcome: tuple = (0.82, 0.06, 0.12)             # authenticated, failed, abandoned
    three_ds_pass_absent: float = 0.04                       # pass rate when the holder isn't there
    client_retry_p: float = 0.02                             # same idempotency key resent
    client_retry_delay: dist.Dist = dist.lognormal(median_s=3, sigma=1.2, max_s=120)
    auth_validity_days: int = 7


@dataclass(frozen=True)
class Risk:
    """merchant_risk shard rules; consumed by kernels.risk_decide."""
    window: str = "1h"                                       # 60 one-minute buckets
    small_amount: int = 500                                  # cents; "tiny" authorization
    small_burst: int = 20                                    # tiny auths / merchant / hour tolerated
    max_card_auths_1h: int = 6                               # hard velocity rule per card
    device_free: int = 3                                     # auths / device / hour before scoring
    w_card: int = 12
    w_device: int = 10
    w_small_burst: int = 35
    w_cross_border: int = 15
    w_prepaid: int = 8
    w_amount: int = 6                                        # per doubling over the MCC median
    score_noise: int = 12                                    # unobserved signals
    challenge_at: int = 60
    decline_at: int = 90


@dataclass(frozen=True)
class Lifecycle:
    """Capture, settlement, refunds and disputes; machines and kernels.refund_flow."""
    capture_p: float = 0.94
    void_p: float = 0.035
    capture_delay: dict = field(default_factory=lambda: {
        "7011": dist.gamma(mean_days=3.0, shape=1.5),        # hotels: at checkout
        "4722": dist.gamma(mean_days=2.0, shape=1.2),        # travel: at ticketing
        "5651": dist.lognormal(median_h=20, sigma=0.8),      # apparel: at shipment
        "5732": dist.lognormal(median_h=18, sigma=0.8),
        "5399": dist.lognormal(median_h=16, sigma=0.9),
        "otherwise": dist.lognormal(median_s=90, sigma=1.5),  # immediate capture
    })
    partial_capture_p: float = 0.05
    late_capture_p: float = 0.3                              # merchant still tries after expiry
    fixed_fee: int = 30                                      # cents, on top of the MDR
    settlement_cutoff: str = "02:00Z"                        # daily batch
    refund_delay: dist.Dist = dist.gamma(mean_days=9, shape=1.3, max_days=90)
    full_refund_p: float = 0.6
    extra_refund_p: float = 0.15                             # another partial refund follows
    max_refunds: int = 3
    client_retry_p: float = 0.02
    client_retry_delay: dist.Dist = dist.lognormal(median_s=3, sigma=1.2, max_s=120)
    dispute_p: dict = field(default_factory=lambda: {
        "5815": 0.009, "5968": 0.010, "4722": 0.007, "5732": 0.006, "5947": 0.007,
        "otherwise": 0.0035,
    })
    dispute_delay: dist.Dist = dist.gamma(mean_days=24, shape=1.4, max_days=118)
    dispute_reason_mix: tuple = (0.30, 0.20, 0.15, 0.05, 0.10, 0.20)   # DISPUTE_REASONS order
    contest_p: float = 0.72
    win_p: dict = field(default_factory=lambda: {
        "fraud": 0.30, "not_received": 0.50, "not_as_described": 0.40, "duplicate": 0.60,
        "credit_not_processed": 0.35, "subscription_canceled": 0.45,
    })
    evidence_window_days: int = 20
    chargeback_fee: int = 1_500                              # cents


@dataclass(frozen=True)
class Config:
    cardholders: int = 1_000_000                             # population at the end of the span
    initial_share: float = 0.85
    merchants: int = 40_000
    merchant_groups: int = 256                               # merchant_risk shards
    max_live_payments: int = 8_000_000                       # open payments (dispute window 120d)
    household_share_device: float = 0.08
    purchases: Purchases = field(default_factory=Purchases)
    auth: Auth = field(default_factory=Auth)
    risk: Risk = field(default_factory=Risk)
    lifecycle: Lifecycle = field(default_factory=Lifecycle)
    execution_owner: str = "cardholder_id"                   # overlays may group members (rings)


def _lose_p(win_p: dict) -> dict:
    return {reason: round(1.0 - p, 6) for reason, p in win_p.items()}


# --------------------------------------------------------------------------- pack
def define(p: Pack, cfg: Config) -> None:
    pu, a, rk, lf = cfg.purchases, cfg.auth, cfg.risk, cfg.lifecycle

    # ---------------------------------------------------------------- read inputs
    mcc = p.table("mcc", key="mcc", mutable=False, doc="Merchant category profiles", cols={
        "label": cat(*(v[0] for v in MCC.values())),
        "median_amount": amount(asset="USD"),
        "sigma": f64(),
        "ecom_share": f64(),
        "refund_p": f64(),
        "risk_base": i16(),
    }, source=std.rows({code: dict(zip(("label", "median_amount", "sigma", "ecom_share",
                                         "refund_p", "risk_base"), v)) for code, v in MCC.items()}))

    merchant = p.table("merchant", key="merchant_id", mutable=False, doc="Merchants we acquire for",
                       cols={
        "mcc": cat(*MCCS),
        "country": cat(*COUNTRIES),
        "size": cat(*SIZES),
        "merchant_group": i16(),
        "mdr_bps": i16(),                                    # merchant discount rate
        "refund_limit_daily": amount(asset="USD"),
    }, source=std.catalog(
        n=cfg.merchants,
        mcc=dist.categorical({"5411": .14, "5812": .16, "5541": .05, "5651": .12, "5732": .07,
                              "5815": .08, "5968": .06, "4722": .03, "7011": .04, "5399": .15,
                              "8398": .04, "5947": .06}),
        country=dist.categorical({"US": .42, "GB": .12, "DE": .1, "FR": .08, "CA": .07,
                                  "BR": .08, "IN": .07, "other": .06}),
        size=dist.categorical({"small": .72, "mid": .2, "large": .07, "enterprise": .01}),
        group=dist.uniform_int(0, cfg.merchant_groups - 1),
        mdr_bps=std.by_column("size", {"small": 290, "mid": 260, "large": 220, "enterprise": 180}),
        refund_limit_daily=std.by_column("size", {"small": 200_000, "mid": 2_000_000,
                                                  "large": 20_000_000, "enterprise": 200_000_000}),
        weight=std.by_column("size", {"small": dist.zipf(s=1.1), "mid": dist.zipf(s=1.1, scale=8),
                                      "large": dist.zipf(s=1.1, scale=60),
                                      "enterprise": dist.zipf(s=1.1, scale=400)}),
    ))

    card = p.table("card", key="card_id", mutable=False, doc="Card tokens and their BIN data",
                   cols={
        "bin": i32(min=100_000, max=999_999),
        "brand": cat(*BRANDS),
        "funding": cat(*FUNDING),
        "issuer_country": cat(*COUNTRIES),
        "status": cat(*CARD_STATUS),                         # as the issuer knows it
        "issued_at": ts(),
    })

    device = p.table("device", key="device_id", mutable=False, doc="Online device fingerprints",
                     cols={
        "os": cat("ios", "android", "windows", "macos", "linux"),
        "kind": cat("phone", "tablet", "desktop"),
        "ip_country": cat(*COUNTRIES),
        "first_seen": ts(),
    })

    # ---------------------------------------------------------------- owner state
    cardholder = p.table("cardholder", key="cardholder_id", mutable=True, export=False,
                         doc="A person with cards; unobservable to an acquirer, kept for labels",
                         cols={
        "joined_at": ts(),
        "country": cat(*COUNTRIES),
        "segment": cat("light", "regular", "heavy"),
        "rate_30d": f64(),                                   # expected purchases at our merchants
        "purchases": i32(),
        "last_purchase_at": opt(ts()),
        "status": cat("active", "dormant", "closed"),
    })

    payment = p.table("payment", key="payment_id", mutable=True, doc="One card payment", cols={
        "card_id": ref("card"),
        "merchant_id": ref("merchant"),
        "device_id": opt(ref("device")),
        "mcc": cat(*MCCS),                                   # denormalized at creation
        "channel": cat(*CHANNELS),
        "amount": amount(asset="USD"),                       # requested
        "authorized": amount(asset="USD"),
        "captured": amount(asset="USD"),
        "captured_at": opt(ts()),
        "fee": amount(asset="USD"),
        "refunded": amount(asset="USD"),
        "refund_hold": amount(asset="USD"),                  # owner-side hold while risk decides
        "disputed": amount(asset="USD"),                     # locked by the open dispute
        "charged_back": amount(asset="USD"),
        "status": cat(*PAYMENT_STATUS),
        "auth_result": cat(*RESULTS),                        # first answer, for idempotent replays
        "auth_expires_at": opt(ts()),
        "three_ds": boolean(),
        "dispute_open": boolean(),
        "disputes": i16(),
        "idem_key": ref("idempotency_key"),
        "holder_present": boolean(export=False),             # the real cardholder is paying
    })
    refund = p.table("refund", key="refund_id", mutable=True, child_of="payment", cols={
        "amount": amount(asset="USD"), "idem_key": ref("idempotency_key"),
        "status": cat("requested", "succeeded", "rejected"),
    })
    dispute = p.table("dispute", key="dispute_id", mutable=True, child_of="payment", cols={
        "reason": cat(*DISPUTE_REASONS), "amount": amount(asset="USD"), "opened_at": ts(),
        "status": cat("opened", "evidence", "won", "lost", "charged_back"),
    })

    p.owner("cardholder", table="cardholder", execution_owner=cfg.execution_owner,
            max_live=cfg.cardholders)
    p.owner("payment", table="payment", max_live=cfg.max_live_payments,
            children=["refund", "dispute"])                  # created by creation messages only

    p.population(
        cardholder, n=cfg.cardholders,
        initial=cfg.initial_share,
        arrivals=dist.poisson_daily(weekly=(1.0, 1.0, 1.0, 1.0, 1.05, 1.1, 0.95), trend=0.001),
        attrs={
            "country": dist.categorical({"US": .45, "GB": .12, "DE": .1, "FR": .08, "CA": .07,
                                         "BR": .07, "IN": .06, "other": .05}),
            "segment": dist.categorical({"light": .55, "regular": .35, "heavy": .10}),
            "rate_30d": std.by_column("segment", {"light": dist.gamma(mean=1.2, shape=1.5),
                                                  "regular": dist.gamma(mean=4.0, shape=2.0),
                                                  "heavy": dist.gamma(mean=14.0, shape=2.5)}),
        },
        refs={
            "card": std.cards(per_holder=dist.categorical({1: .55, 2: .33, 3: .12}), table=card,
                              brand=dist.categorical({"visa": .52, "mastercard": .33,
                                                      "amex": .1, "discover": .05}),
                              funding=dist.categorical({"credit": .5, "debit": .44,
                                                        "prepaid": .06}),
                              issuer_country="holder.country", status="active"),
            "device": std.devices(per_user=dist.categorical({1: .6, 2: .3, 3: .1}),
                                  table=device, share=cfg.household_share_device),
        },
    )

    # ---------------------------------------------------------------- shard
    risk = p.shard("merchant_risk", key="merchant_group", n=cfg.merchant_groups, config=rk,
                   doc="Authorization screening and refund headroom for one merchant group",
                   state={
        "card_auths": f"window_count[card, {rk.window}/1m]",      # per card, this group only
        "device_auths": f"window_count[device, {rk.window}/1m]",
        "merchant_auths": f"window_count[merchant, {rk.window}/1m]",
        "merchant_small": f"window_count[merchant, {rk.window}/1m]",
        "merchant_declines": f"window_count[merchant, {rk.window}/1m]",
        "refund_day": "i32[merchant]",                             # lazy daily reset per merchant
        "refund_sum": "i64[merchant]",
    }, capacity={"card": 400_000, "device": 200_000})              # hard caps, reported

    authorize = p.request(
        "authorize", frm="payment", to="merchant_risk", handler=k.risk_decide,
        payload={"payment_id": ref("payment"), "card_id": ref("card"),
                 "merchant_id": ref("merchant"), "device_id": opt(ref("device")),
                 "amount": amount(asset="USD"), "mcc": cat(*MCCS), "channel": cat(*CHANNELS),
                 "funding": cat(*FUNDING), "cross_border": boolean()},
        responses={"approve": k.R_APPROVE, "decline": k.R_DECLINE, "challenge": k.R_CHALLENGE},
        latency=dist.shifted_lognormal(min_ms=80, median_ms=110, max_ms=1_500))

    refund_check = p.request(
        "refund_check", frm="payment", to="merchant_risk", handler=k.refund_check,
        payload={"payment_id": ref("payment"), "refund_id": ref("refund"),
                 "merchant_id": ref("merchant"), "amount": amount(asset="USD")},
        responses={"approved": k.R_REFUND_OK, "declined": k.R_REFUND_DECLINED},
        latency=dist.shifted_lognormal(min_ms=80, median_ms=120, max_ms=1_500))

    # ---------------------------------------------------------------- money, accumulated only
    # Kernels write these through generated emitters: out.post_ledger, out.accumulate_settlement
    std.ledger(p, "ledger", owner="payment", asset="USD", accounts=k.ACCOUNTS,
               into="postings")                              # rows: payment_id, entry_id, account,
                                                             #       side, amount, cause_id
    p.accumulator("settlement", key=("merchant_id", "batch_date"),
                               cutoff=lf.settlement_cutoff, into="settlement", cols={
        "gross": amount(asset="USD"), "refunds": amount(asset="USD"),
        "chargebacks": amount(asset="USD"), "fees": amount(asset="USD"),
    })                                                       # additive; no decision reads it

    # ---------------------------------------------------------------- events
    pay_id = {"payment_id": ref("payment")}
    p.event("authorization_requested", owner="payment", doc="A merchant asks us to authorize",
            cols={
        **pay_id, "card_id": ref("card"), "merchant_id": ref("merchant"),
        "device_id": opt(ref("device")), "amount": amount(asset="USD"), "mcc": cat(*MCCS),
        "channel": cat(*CHANNELS), "bin": i32(), "card_brand": cat(*BRANDS),
        "funding": cat(*FUNDING), "card_country": cat(*COUNTRIES),
        "merchant_country": cat(*COUNTRIES), "idempotency_key": ref("idempotency_key"),
    })
    p.event("risk_evaluated", shard="merchant_risk", doc="Risk decision at the shard's decision time",
            cols={
        "merchant_group": i16(), **pay_id, "card_id": ref("card"), "merchant_id": ref("merchant"),
        "device_id": opt(ref("device")), "amount": amount(asset="USD"), "score": i16(),
        "decision": cat("approve", "decline", "challenge"),
        "rule": cat("none", "score", "velocity_card", "velocity_device", "small_burst"),
        "card_auths_1h": i32(), "device_auths_1h": i32(), "merchant_small_1h": i32(),
    })
    p.event("three_ds_challenged", owner="payment", cols={
        **pay_id, "card_id": ref("card"), "merchant_id": ref("merchant"), "risk_score": i16(),
        "protocol": cat("2.1", "2.2"),
    })
    p.event("three_ds_completed", owner="payment", cols={
        **pay_id, "result": cat("authenticated", "failed", "abandoned"), "duration_ms": i32(),
    })
    p.event("authorization_approved", owner="payment", cols={
        **pay_id, "card_id": ref("card"), "merchant_id": ref("merchant"),
        "amount": amount(asset="USD"), "auth_code": i32(), "three_ds": boolean(),
        "risk_score": i16(), "expires_at": ts(),
    })
    p.event("authorization_declined", owner="payment", cols={
        **pay_id, "card_id": ref("card"), "merchant_id": ref("merchant"),
        "amount": amount(asset="USD"), "decline_code": cat(*DECLINE_CODES),
        "source": cat("risk", "authentication", "issuer"), "risk_score": i16(),
    })
    p.event("idempotent_replay", owner="payment", doc="A retried request returns the first result",
            cols={
        **pay_id, "operation": cat("authorization", "refund"),
        "idempotency_key": ref("idempotency_key"), "original_result": cat(*RESULTS),
        "refund_id": opt(ref("refund")),
    })
    p.event("authorization_voided", owner="payment", cols={
        **pay_id, "merchant_id": ref("merchant"), "amount": amount(asset="USD"),
        "reason": cat("order_canceled", "out_of_stock", "customer_request"),
    })
    p.event("authorization_expired", owner="payment", cols={
        **pay_id, "merchant_id": ref("merchant"), "amount": amount(asset="USD"),
    })
    p.event("capture_succeeded", owner="payment", cols={
        **pay_id, "card_id": ref("card"), "merchant_id": ref("merchant"),
        "amount": amount(asset="USD"), "authorized": amount(asset="USD"), "partial": boolean(),
        "fee": amount(asset="USD"),
    })
    p.event("capture_rejected", owner="payment", cols={
        **pay_id, "merchant_id": ref("merchant"), "amount": amount(asset="USD"),
        "reason": cat("authorization_expired"),
    })
    p.event("payment_settled", owner="payment", doc="Included in the daily settlement batch", cols={
        **pay_id, "merchant_id": ref("merchant"), "batch_date": ts(),
        "gross": amount(asset="USD"), "fee": amount(asset="USD"), "net": amount(asset="USD"),
    })
    p.event("refund_requested", owner="payment", cols={
        **pay_id, "refund_id": ref("refund"), "merchant_id": ref("merchant"),
        "amount": amount(asset="USD"), "partial": boolean(),
        "idempotency_key": ref("idempotency_key"),
    })
    p.event("refund_succeeded", owner="payment", cols={
        **pay_id, "refund_id": ref("refund"), "merchant_id": ref("merchant"),
        "amount": amount(asset="USD"), "refunded_total": amount(asset="USD"),
    })
    p.event("refund_rejected", owner="payment", cols={
        **pay_id, "refund_id": ref("refund"), "merchant_id": ref("merchant"),
        "amount": amount(asset="USD"), "reason": cat("dispute_open", "merchant_limit"),
    })
    p.event("refund_screened", shard="merchant_risk", doc="Refund headroom decision", cols={
        "merchant_group": i16(), **pay_id, "refund_id": ref("refund"),
        "merchant_id": ref("merchant"), "amount": amount(asset="USD"),
        "refunded_today": amount(asset="USD"), "daily_limit": amount(asset="USD"),
        "decision": cat("approved", "declined"),
    })
    p.event("dispute_opened", owner="payment", cols={
        **pay_id, "dispute_id": ref("dispute"), "card_id": ref("card"),
        "merchant_id": ref("merchant"), "reason": cat(*DISPUTE_REASONS),
        "amount": amount(asset="USD"), "days_since_capture": i16(), "respond_by": ts(),
    })
    p.event("dispute_evidence_submitted", owner="payment", cols={
        **pay_id, "dispute_id": ref("dispute"),
        "evidence": cat("delivery_proof", "receipt", "usage_logs", "refund_policy", "avs_cvv_match"),
    })
    p.event("dispute_won", owner="payment", cols={
        **pay_id, "dispute_id": ref("dispute"), "amount": amount(asset="USD"),
    })
    p.event("dispute_lost", owner="payment", cols={
        **pay_id, "dispute_id": ref("dispute"), "amount": amount(asset="USD"),
        "resolution": cat("accepted", "issuer_ruled"),
    })
    p.event("chargeback_posted", owner="payment", cols={
        **pay_id, "dispute_id": ref("dispute"), "merchant_id": ref("merchant"),
        "amount": amount(asset="USD"), "fee": amount(asset="USD"),
    })
    # postings rows are declared by std.ledger; settlement rows by p.accumulator

    # ---------------------------------------------------------------- processes
    p.process("cardholder_purchases", owner="cardholder", kernel=k.cardholder_purchases, config=pu,
              start=p.on_created("cardholder"), creates=("payment",),
              reads={"merchant": merchant, "mcc": mcc, "card": card, "device": device},
              commands=k.PURCHASE_COMMANDS)

    p.process("authorize_payment", owner="payment", kernel=k.authorize_payment, config=a,
              start=p.on_created("payment"), requests={"authorize": authorize},
              reads={"merchant": merchant, "card": card}, commands=k.AUTH_COMMANDS)

    # Capture races expiry. At the same instant, expiry runs first (declared precedence), so a
    # capture at exactly auth_expires_at counts as expired; leaving the state cancels the rest.
    lc = p.machine("payment_lifecycle", owner="payment", config=lf,
                   start=p.on_event("authorization_approved"), initial="authorized")
    lc.state("authorized",
             branch={
                 "captured": (lf.capture_p, std.by_column("mcc", lf.capture_delay), k.capture),
                 "voided":   (lf.void_p, dist.lognormal(median_h=5, sigma=1.0), k.void_authorization),
             },
             otherwise="stay",                               # no merchant action: expiry decides
             timer={"expired": (f"{a.auth_validity_days}d", k.expire_authorization)},
             precedence=("expired", "captured", "voided"))
    lc.state("expired", branch={
        "late_capture": (lf.late_capture_p, dist.exp(mean_h=18), k.reject_late_capture),
        "otherwise":    (None, None, None),
    })
    lc.state("captured", branch={
        "settled": (1.0, std.next_cutoff(lf.settlement_cutoff), k.settle_payment),
    })
    lc.state("settled", branch={
        "disputed":  (std.by_column("mcc", lf.dispute_p), lf.dispute_delay, k.open_dispute),
        "otherwise": (None, None, None),
    }, on_reject="otherwise")                                # nothing left to dispute
    lc.final("voided", "late_capture", "disputed", "otherwise")

    # Refunds: hold on the payment, merchant_risk decides headroom, then commit or release
    p.process("refund_flow", owner="payment", kernel=k.refund_flow, config=lf,
              start=p.on_event("capture_succeeded"), requests={"refund_check": refund_check},
              reads={"merchant": merchant, "mcc": mcc}, commands=k.REFUND_COMMANDS)

    # Dispute: a child process of the payment, one instance per dispute row
    d = p.machine("dispute", owner="payment", instance="dispute", config=lf,
                  start=p.on_event("dispute_opened"), initial="opened")
    d.state("opened", branch={
        "evidence": (lf.contest_p, dist.gamma(mean_days=8, shape=2.0, max_days=lf.evidence_window_days),
                     k.submit_evidence),
        "lost":     (1 - lf.contest_p, dist.gamma(mean_days=6, shape=1.5,
                                                  max_days=lf.evidence_window_days),
                     k.accept_dispute),
    })
    d.state("evidence", branch={
        "won":  (std.by_column("reason", lf.win_p), dist.gamma(mean_days=30, shape=3.0, max_days=75),
                 k.win_dispute),
        "lost": (std.by_column("reason", _lose_p(lf.win_p)),
                 dist.gamma(mean_days=30, shape=3.0, max_days=75), k.lose_dispute),
    })
    d.state("lost", branch={
        "charged_back": (1.0, dist.gamma(mean_days=2, shape=2.0, max_days=10), k.post_chargeback),
    })
    d.final("won", "charged_back")

    # ---------------------------------------------------------------- enrichment
    # Cross-owner features, computed after each step seals on canonical order; go to golden/
    p.feature("card_distinct_merchants_24h",
              std.rolling_distinct("merchant_id", by="card_id", window="24h"),
              on=["authorization_requested"], into="golden")
    p.feature("device_distinct_cards_1h",
              std.rolling_distinct("card_id", by="device_id", window="1h"),
              on=["authorization_requested"], into="golden")
    p.feature("merchant_decline_rate_1h",
              std.rolling_ratio("authorization_declined",
                                of=("authorization_approved", "authorization_declined"),
                                by="merchant_id", window="1h"),
              on=["authorization_requested"], into="golden")
    p.feature("card_auths_7d", std.rolling_count("authorization_requested", by="card_id",
                                                 window="7d"),
              on=["authorization_requested"], into="golden")

    # ---------------------------------------------------------------- laws
    p.check("chk.capture_le_authorized",
            law.sum_le("capture_succeeded.amount", "authorization_approved.amount", by="payment_id"),
            required=True)
    p.check("chk.refund_le_captured",
            law.sum_le(("refund_succeeded.amount", "chargeback_posted.amount"),
                       "capture_succeeded.amount", by="payment_id"), required=True)
    p.check("chk.no_capture_after_expiry",
            law.before("capture_succeeded", deadline="authorization_approved.expires_at",
                       key="payment_id", strict=True), required=True)
    p.check("chk.payment_lifecycle", law.lifecycle("payment_id", edges={   # refund and dispute
        "authorization_requested": ("three_ds_challenged", "authorization_approved",  # events have
                                    "authorization_declined"),                         # own laws
        "three_ds_challenged": ("three_ds_completed",),
        "three_ds_completed": ("authorization_approved", "authorization_declined"),
        "authorization_approved": ("capture_succeeded", "authorization_voided",
                                   "authorization_expired"),
        "authorization_expired": ("capture_rejected",),
        "capture_succeeded": ("payment_settled",),
    }), required=True)
    p.check("chk.dispute_lifecycle", law.lifecycle("dispute_id", edges={
        "dispute_opened": ("dispute_evidence_submitted", "dispute_lost"),
        "dispute_evidence_submitted": ("dispute_won", "dispute_lost"),
        "dispute_lost": ("chargeback_posted",),
    }), required=True)
    p.check("chk.no_refund_while_disputed",
            law.not_within("refund_succeeded", open="dispute_opened",
                           close=("dispute_won", "chargeback_posted"), key="payment_id"),
            required=True)
    p.check("chk.refund_hold_resolved",
            law.resolved("refund_requested", by=("refund_succeeded", "refund_rejected"),
                         key="refund_id", within="1h"), required=True)
    p.check("chk.holds_never_negative",
            law.never_negative(("payment.refund_hold", "payment.disputed")), required=True)
    p.check("chk.one_dispute_per_payment",
            law.at_most_once("dispute_opened", key="payment_id"), required=True)
    p.check("chk.postings_balance",
            law.balanced("postings", by=("payment_id", "entry_id")), required=True)
    p.check("chk.settlement_matches_events",
            law.accumulator_matches("settlement.gross", "payment_settled.gross",
                                    by="merchant_id", per="batch_date"), required=True)
    p.check("chk.idempotency",
            law.idempotent(first=("authorization_requested", "refund_requested"),
                           replay="idempotent_replay",
                           key="idempotency_key",
                           result_from=("authorization_approved", "authorization_declined",
                                        "refund_succeeded", "refund_rejected")), required=True)
    p.check("chk.one_risk_decision",
            law.exactly_once("risk_evaluated", per="authorization_requested", key="payment_id"),
            required=True)
    p.check("chk.risk_counters_consistent",
            law.counter_matches("risk_evaluated.card_auths_1h", events="risk_evaluated",
                                key=("merchant_group", "card_id"), window=rk.window,
                                buckets="1m"), required=True)

    # ---------------------------------------------------------------- extension points
    # Named actions overlays may call (validate checks them against the resolved plan)
    p.expose(purchase=k.place_purchase, open_dispute=k.open_dispute)
