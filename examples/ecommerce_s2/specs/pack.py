"""E-commerce + payments S2 slice (spec §18 S2).

Partitions
    owner  user        one shopper: profile, credit hold, a cart of up to four lines
    shard  inventory   one inventory group: on_hand / reserved per SKU and a 64-slot hold table

Boundaries (immutable, latency >= delta)
    user -> inventory  reserve (request: granted / rejected with hold id and slot)  delta 150 ms
    user -> inventory  commit, release (one-way messages carrying the hold)         delta 150 ms

Created owners
    payment            one payment, created by a checkout or a bill (D54); lifecycle in Local

The bonus pool and campaigns are added by task 15 of the S2 plan.
"""

from dataclasses import dataclass, field

from neorisk_simkit.spec import Pack, PackError, dist, law, std
from neorisk_simkit.spec.types import amount, boolean, cat, i16, i32, i64, opt, ref, ts

from . import kernels as k

PACK = "ecommerce_s2"
SCHEMA_VERSION = 1

CATEGORIES = (
    "apparel", "shoes", "beauty", "home", "kitchen", "garden", "toys", "baby", "books",
    "music", "video_games", "electronics", "phones", "computers", "office", "pets", "sports",
    "outdoors", "auto", "tools", "grocery", "health", "jewelry", "luggage",
)
CHANNELS = ("web", "app")
ACQUISITION = ("organic", "search_ad", "social_ad", "affiliate")
METHODS = ("card", "wallet", "bnpl")
ACCOUNTS = ("customer_funds", "customer_held", "merchant", "platform_fees", "refunds_payable",
            "dispute_reserve")


@dataclass(frozen=True)
class Journey:
    """Shopper behavior; consumed by kernels.shopper."""
    signup_delay: dist.Dist = dist.exp(mean_s=3600)
    session_gap_alpha: float = 1.2
    session_gap_min_h: float = 30.0
    views_mean: float = 4.0
    view_gap: dist.Dist = dist.exp(mean_s=40)
    add_to_cart_p: float = 0.25             # per view; a cart holds up to kernels.CART lines
    hot_skus: int = 50                      # catalog rows [0, hot_skus) form SKU group 0
    hot_pick_p: float = 0.05                # per view: look at a hot SKU
    checkout_p: float = 0.5                 # per session end with a non-empty cart
    checkout_delay: dist.Dist = dist.exp(mean_s=25)
    abandon_p: float = 0.02                 # a fully granted checkout is abandoned (TTL frees)
    substitute_p: float = 0.45
    bill_gap: dist.Dist = dist.exp(mean_days=20)    # between a shopper's bill payments (D54)
    bill_median: float = 6_000.0
    bill_sigma: float = 0.8


@dataclass(frozen=True)
class Desk:
    """Inventory desk; consumed by kernels.inventory_desk."""
    hold_ttl_s: int = 600


@dataclass(frozen=True)
class PayLife:
    """Payment lifecycle; consumed by kernels.payment_life."""
    decline_p: float = 0.03
    capture_p: float = 0.93
    capture_delay: dist.Dist = dist.lognormal(median_s=3600, sigma=1.0)
    auth_expiry_s: int = 7 * 86_400          # capture races this expiry (§09)
    fee_bps: int = 290
    dispute_window_days: int = 90            # the 90-day dispute timer (§10 S2)
    refund_p: float = 0.04                   # per capture, then again per refund request
    refund_gap: dist.Dist = dist.exp(mean_days=9)
    max_refunds: int = 3                     # refund requests per payment (idempotency keys)
    refund_median: float = 2_500.0
    refund_sigma: float = 0.9
    refund_settle: dist.Dist = dist.lognormal(median_s=86_400, sigma=0.5)
    refund_fail_p: float = 0.02              # the processor fails a refund: the hold is released
    duplicate_p: float = 0.05                # the merchant retries a refund with the same key
    duplicate_gap: dist.Dist = dist.exp(mean_s=30)
    dispute_p: float = 0.006                 # per capture, inside the dispute window
    dispute_delay: dist.Dist = dist.gamma(mean_days=21)
    dispute_resolve: dist.Dist = dist.gamma(mean_days=30)
    dispute_win_p: float = 0.55


@dataclass(frozen=True)
class Config:
    users: int = 20_000
    initial_share: float = 0.6
    referred_share: float = 0.15
    skus: int = 5_000
    sku_groups: int = 64
    restock_period: str = "7d"
    household_share_device: float = 0.12
    journey: Journey = field(default_factory=Journey)
    desk: Desk = field(default_factory=Desk)
    payments_live_ratio: float = 1.5
    pay: PayLife = field(default_factory=PayLife)


def define(p: Pack, cfg: Config) -> None:
    j = cfg.journey
    if cfg.pay.max_refunds > k.IDEM_SLOTS:     # one idempotency slot per refund request
        raise PackError(f"pay.max_refunds = {cfg.pay.max_refunds} exceeds the "
                        f"{k.IDEM_SLOTS} idempotency slots of a payment")
    # ---------------------------------------------------------------- catalog and devices
    sku = p.table("sku", key="sku_id", doc="Catalog, fixed for the run", cols={
        "category": cat(*CATEGORIES), "price": amount(asset="USD"), "sku_group": i16()},
        source=std.catalog(n=cfg.skus, category=dist.categorical(
            {c: 1 / len(CATEGORIES) for c in CATEGORIES}),
            price=dist.lognormal_minor(median=2_500, sigma=0.9, min=199, max=200_000),
            group=dist.uniform_int(1, cfg.sku_groups - 1), weight=dist.zipf(s=1.07),
            hot_rows=j.hot_skus))
    device = p.table("device", key="device_id", doc="Shopper devices", cols={
        "os": cat("ios", "android", "windows", "macos", "linux"),
        "kind": cat("phone", "tablet", "desktop"), "first_seen": ts()})
    # ---------------------------------------------------------------- shoppers
    user = p.table("user", key="user_id", mutable=True, doc="A shopper", cols={
        "age_band": cat("18-24", "25-34", "35-44", "45-54", "55+"),
        "acquisition": cat(*ACQUISITION), "status": cat("active", "dormant"),
        "referred": boolean(), "credit_limit": amount(asset="USD"),
        "held": amount(asset="USD")})
    p.ids("session", "checkout", "hold")
    p.owner("user", table=user, max_live=cfg.users, retire_when_idle=False)
    p.population(
        user, n=cfg.users, initial=cfg.initial_share,
        arrivals=dist.poisson_daily(weekly=(1.0, 0.95, 0.95, 1.0, 1.1, 1.3, 1.25), trend=0.002),
        attrs={"age_band": dist.categorical({"18-24": .17, "25-34": .31, "35-44": .24,
                                             "45-54": .16, "55+": .12}),
               "acquisition": dist.categorical({"organic": .55, "search_ad": .2,
                                                "social_ad": .15, "affiliate": .1}),
               "referred": dist.categorical({0: 1 - cfg.referred_share,
                                             1: cfg.referred_share}),
               "credit_limit": dist.uniform_int(20_000, 400_000)},
        refs={"device": std.devices(per_user=dist.categorical({1: .6, 2: .3, 3: .1}),
                                    table=device, share=cfg.household_share_device)})
    # ---------------------------------------------------------------- inventory
    inventory = p.shard("inventory", key="sku_group", n=cfg.sku_groups, items=sku,
                        doc="Stock per inventory group; group 0 is the hot group",
                        state={"on_hand": "i32[sku]", "reserved": "i32[sku]"},
                        init=std.stock(initial=dist.negbinom(mean=40, disp=0.7), by_weight=8.0))
    lat = dist.shifted_lognormal(min_ms=150, median_ms=240)
    reserve = p.request("reserve", frm="user", to=inventory,
                        payload={"sku_id": ref("sku"), "quantity": i16(), "line": i16()},
                        response_payload={"hold_id": opt(ref("hold")), "slot": i32(),
                                          "line": i16()},
                        responses=("granted", "rejected"), latency=lat)
    held = {"sku_id": ref("sku"), "quantity": i16(), "hold_id": ref("hold"), "slot": i32()}
    commit = p.message("commit", frm="user", to=inventory, payload=held, latency=lat)
    release = p.message("release", frm="user", to=inventory, payload=held, latency=lat)
    # ---------------------------------------------------------------- events
    u = {"user_id": ref("user")}
    p.event("user_signed_up", owner="user", cols={
        **u, "device_id": ref("device"), "acquisition": cat(*ACQUISITION),
        "referred": boolean()})
    p.event("session_started", owner="user", cols={
        **u, "session_id": ref("session"), "device_id": ref("device"), "channel": cat(*CHANNELS)})
    p.event("product_viewed", owner="user", cols={
        **u, "session_id": ref("session"), "sku_id": ref("sku"), "device_id": ref("device"),
        "position": i16(), "channel": cat(*CHANNELS), "category": cat(*CATEGORIES),
        "price": amount(asset="USD")})
    p.event("cart_item_added", owner="user", cols={
        **u, "session_id": ref("session"), "sku_id": ref("sku"), "quantity": i16(),
        "unit_price": amount(asset="USD")})
    p.event("checkout_started", owner="user", doc="Credit held; one reserve per cart line",
            cols={**u, "session_id": ref("session"), "checkout_id": ref("checkout"),
                  "lines": i16(), "subtotal": amount(asset="USD"),
                  "hold_after": amount(asset="USD")})
    p.event("checkout_failed", owner="user", cols={
        **u, "checkout_id": ref("checkout"), "reason": cat("out_of_stock", "credit_limit"),
        "sku_id": opt(ref("sku")), "hold_after": amount(asset="USD")})
    p.event("checkout_abandoned", owner="user", doc="Every line granted, never committed",
            cols={**u, "checkout_id": ref("checkout"), "hold_after": amount(asset="USD")})
    p.event("checkout_succeeded", owner="user", cols={
        **u, "checkout_id": ref("checkout"), "payment_id": ref("payment"),
        "amount": amount(asset="USD"), "hold_after": amount(asset="USD")})
    # ---------------------------------------------------------------- payments (§09)
    payment = p.table("payment", key="payment_id", mutable=True, doc="A card payment", cols={
        "user_id": ref("user"), "checkout_id": opt(ref("checkout")),
        "amount": amount(asset="USD"), "method": cat(*METHODS),
        "source": cat("checkout", "bill")})
    p.owner("payment", table=payment, max_live=max(1_000, int(cfg.users * cfg.payments_live_ratio)))
    p.accumulator("platform_fees", amount(asset="USD"))
    pay_id = {"payment_id": ref("payment")}
    p.event("payment_authorized", owner="payment", cols={
        **pay_id, "user_id": ref("user"), "amount": amount(asset="USD"),
        "method": cat(*METHODS), "source": cat("checkout", "bill")})
    p.event("payment_declined", owner="payment", cols={
        **pay_id, "user_id": ref("user"), "amount": amount(asset="USD")})
    p.event("payment_captured", owner="payment", cols={
        **pay_id, "amount": amount(asset="USD"), "fee": amount(asset="USD")})
    p.event("payment_expired", owner="payment", cols={**pay_id, "amount": amount(asset="USD")})
    p.postings("ledger", owner="payment", doc="Double-entry postings of payment events", cols={
        **pay_id, "account": cat(*ACCOUNTS), "side": cat("debit", "credit"),
        "amount": amount(asset="USD")})
    p.event("bill_payment_started", owner="user", cols={
        **u, "payment_id": ref("payment"), "amount": amount(asset="USD")})
    # refunds (§09): a refund holds against the remainder, then settles or fails; a repeated
    # idempotency key returns the first result; a dispute is a sub-lifecycle of the payment (D51)
    p.ids("refund")
    refund = {**pay_id, "refund_id": ref("refund")}
    p.event("refund_requested", owner="payment", doc="Held against captured - refunded - held",
            cols={**refund, "amount": amount(asset="USD")})
    p.event("refund_settled", owner="payment", doc="The hold is committed", cols={
        **refund, "amount": amount(asset="USD"), "refunded_after": amount(asset="USD")})
    p.event("refund_failed", owner="payment", doc="The processor failed; the hold is released",
            cols={**refund, "amount": amount(asset="USD")})
    p.event("refund_rejected", owner="payment", cols={
        **refund, "reason": cat("nothing_left", "dispute_open")})
    p.event("refund_replayed", owner="payment", doc="A repeated key returns the first result",
            cols={**refund, "result": cat("requested", "rejected")})
    for name in ("dispute_opened", "dispute_won", "dispute_lost"):
        p.event(name, owner="payment", cols={**pay_id, "amount": amount(asset="USD")})
    p.process("payment_life", owner="payment", kernel=k.payment_life, config=cfg.pay,
              start=p.on_created("payment"), commands=k.PAYMENT_COMMANDS)
    p.check("chk.postings_balanced", law.balanced("ledger"), required=True)
    p.check("chk.one_capture", law.at_most_once("payment_captured", key="payment_id"),
            required=True)
    p.check("chk.refunds_le_captured", law.sum_le(
        "refund_settled.amount", "payment_captured.amount", by="payment_id"), required=True)
    p.check("chk.refund_settles_once", law.at_most_once("refund_settled", key="refund_id"),
            required=True)
    stock = {"sku_group": i16(), "sku_id": ref("sku"), "checkout_id": ref("checkout")}
    p.event("stock_reserved", shard="inventory", cols={
        **stock, "hold_id": ref("hold"), "quantity": i16()})
    p.event("stock_rejected", shard="inventory", cols={
        **stock, "quantity": i16(), "reason": cat("out_of_stock", "busy")})
    p.event("stock_committed", shard="inventory", cols={
        **stock, "hold_id": ref("hold"), "quantity": i16(), "on_hand_after": i32()})
    for name in ("stock_released", "stock_expired", "stock_commit_late"):
        p.event(name, shard="inventory", cols={**stock, "hold_id": ref("hold"),
                                               "quantity": i16()})
    p.event("restocked", shard="inventory", doc="Supplier delivery to an inventory group", cols={
        "sku_group": i16(), "sku_id": ref("sku"), "quantity": i32(min=1), "on_hand_after": i32()})
    # §10 "one hot SKU group taking 5% of checkouts": started checkouts with a line in group 0
    p.accumulator("hot_checkouts", i64())
    # ---------------------------------------------------------------- processes
    p.process("shopper", owner="user", kernel=k.shopper, config=j,
              start=p.on_created("user"), requests={"reserve": reserve},
              messages={"commit": commit, "release": release},
              on_response={("reserve", "granted"): k.R_GRANTED,
                           ("reserve", "rejected"): k.R_REJECTED},
              reads={"sku": sku, "device": device}, refs={"device": "device"},
              commands=k.SHOPPER_COMMANDS)
    p.process("inventory_desk", shard=inventory, kernel=k.inventory_desk, config=cfg.desk,
              on_request={"reserve": k.C_RESERVE},
              on_message={"commit": k.C_COMMIT, "release": k.C_RELEASE},
              reads={"sku": sku}, commands=k.DESK_COMMANDS)
    p.process("restock", shard=inventory, kernel=k.restock, every=cfg.restock_period,
              jitter=dist.normal(mean_h=0, sd_h=18), reads={"sku": sku})
    # ---------------------------------------------------------------- laws (§11)
    p.check("chk.stock_never_negative", law.never_negative("inventory.on_hand"), required=True)
    p.check("chk.reserved_never_negative", law.never_negative("inventory.reserved"),
            required=True)
    p.check("chk.user_hold_never_negative", law.never_negative("user.held"), required=True)
    p.check("chk.holds_resolved", law.resolved(
        "stock_reserved", by=("stock_committed", "stock_released", "stock_expired"),
        key="hold_id", within="15m"), required=True)
