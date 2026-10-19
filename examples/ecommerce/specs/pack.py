"""E-commerce marketplace pack (see brief.md).

Partitions
    owner  user           one shopper: profile, credit and its hold, region, cart scratch
    owner  order          one placed order (created at checkout); runs the fulfillment machine
    shard  inventory      one inventory group: on_hand / reserved per SKU and a 64-slot hold table
    shard  referral_pool  the referral program's budget, reset every `referral.period`

Boundaries (immutable, latency >= delta)
    user -> inventory      reserve (request), commit / release (messages)    delta 150 ms
    user -> referral_pool  claim (request)                                    delta 300 ms
    user -> user           inviter_credit (owner-to-owner, D73)               delta 1 day

Overlays reach the base only through p.expose / p.expose_param / p.expose_owner (§08).
"""

from dataclasses import dataclass, field

from neorisk_simkit.spec import Pack, dist, law, std
from neorisk_simkit.spec.types import amount, boolean, cat, i16, i32, i64, opt, ref, ts

from . import kernels as k

PACK = "ecommerce"
SCHEMA_VERSION = 1

CATEGORIES = (
    "apparel", "shoes", "beauty", "home", "kitchen", "garden", "toys", "baby", "books",
    "music", "video_games", "electronics", "phones", "computers", "office", "pets", "sports",
    "outdoors", "auto", "tools", "grocery", "health", "jewelry", "luggage",
)
CHANNELS = ("web", "app")
ACQUISITION = ("organic", "search_ad", "social_ad", "affiliate", "invite")
REGIONS = tuple(f"r{i:02d}" for i in range(k.N_REGIONS))
CARRIERS = ("ups", "fedex", "usps", "dhl")
RETURN_REASONS = ("size", "damaged", "not_as_described", "changed_mind", "late")
HOLD_SLACK_S = 300


@dataclass(frozen=True)
class Journey:
    """Shopper behavior; consumed by kernels.shopper (ctx.cfg.journey)."""
    signup_delay: dist.Dist = dist.exp(mean_s=3600)
    session_gap_alpha: float = 1.2
    session_gap_min_h: float = 30.0
    views_mean: float = 6.0
    view_gap: dist.Dist = dist.exp(mean_s=40)
    add_to_cart_p: float = 0.18
    checkout_p: float = 0.5                 # per session end with a non-empty cart
    checkout_delay: dist.Dist = dist.exp(mean_s=25)
    substitute_p: float = 0.45
    auth_latency: dist.Dist = dist.lognormal(median_s=2.5, sigma=0.6)
    auth_fail_p: float = 0.03
    credit_use_p: float = 0.9
    move_gap: dist.Dist = dist.exp(mean_days=45)   # address changes (user_state downstream)


@dataclass(frozen=True)
class Referral:
    referred_share: float = 0.06            # population users who arrived through an invite
    inviter_share: float = 0.04             # invitees name an inviter among the first 4%
    min_order: int = 3_000                  # cents; a first order from $30 qualifies
    bonus_each: int = 1_000                 # cents; invitee and inviter
    monthly_budget: int = 25_000_000        # cents per period
    period: str = "30d"


@dataclass(frozen=True)
class Fulfil:
    """Fulfillment machine parameters (branch probabilities are config, not code)."""
    ship_p: float = 0.985
    return_apparel_p: float = 0.18
    return_shoes_p: float = 0.14
    return_p: float = 0.045


@dataclass(frozen=True)
class Desk:
    hold_ttl_s: int = 600


@dataclass(frozen=True)
class PoolCfg:
    budget: int = 25_000_000
    period_us: int = 30 * 86_400_000_000


@dataclass(frozen=True)
class Config:
    users: int = 200_000
    initial_share: float = 0.6
    skus: int = 50_000
    sku_groups: int = 512
    restock_period: str = "7d"
    household_share_device: float = 0.12
    orders_live_ratio: float = 0.5
    journey: Journey = field(default_factory=Journey)
    referral: Referral = field(default_factory=Referral)
    fulfil: Fulfil = field(default_factory=Fulfil)
    desk: Desk = field(default_factory=Desk)


def define(p: Pack, cfg: Config) -> None:
    from neorisk_simkit.spec.project import parse_duration
    r = cfg.referral
    # ---------------------------------------------------------------- read tables
    sku = p.table("sku", key="sku_id", doc="Catalog, fixed for the run", cols={
        "category": cat(*CATEGORIES), "price": amount(asset="USD"), "sku_group": i16()},
        source=std.catalog(n=cfg.skus, category=dist.categorical(
            {c: 1 / len(CATEGORIES) for c in CATEGORIES}),
            price=dist.lognormal_minor(median=2_500, sigma=0.9, min=199, max=200_000),
            group=dist.uniform_int(0, cfg.sku_groups - 1), weight=dist.zipf(s=1.07)))
    device = p.table("device", key="device_id", doc="Shopper devices", cols={
        "os": cat("ios", "android", "windows", "macos", "linux"),
        "kind": cat("phone", "tablet", "desktop"), "first_seen": ts()})
    # ---------------------------------------------------------------- shoppers
    user = p.table("user", key="user_id", mutable=True, doc="A shopper and their wallet", cols={
        "age_band": cat("18-24", "25-34", "35-44", "45-54", "55+"),
        "acquisition": cat(*ACQUISITION), "region": cat(*REGIONS), "referred": boolean(),
        "invited_by": opt(ref("user")), "credit": amount(asset="USD"),
        "held": amount(asset="USD")})
    p.ids("session", "checkout", "hold", "claim")
    p.owner("user", table=user, max_live=cfg.users, retire_when_idle=False)
    n_inviters = max(1, int(cfg.users * cfg.initial_share * r.inviter_share))
    p.population(
        user, n=cfg.users, initial=cfg.initial_share,
        arrivals=dist.poisson_daily(weekly=(1.0, 0.95, 0.95, 1.0, 1.1, 1.3, 1.25), trend=0.002),
        attrs={"age_band": dist.categorical({"18-24": .17, "25-34": .31, "35-44": .24,
                                             "45-54": .16, "55+": .12}),
               "acquisition": dist.categorical({"organic": .55, "search_ad": .2,
                                                "social_ad": .15, "affiliate": .1}),
               "region": dist.categorical({x: 1 / len(REGIONS) for x in REGIONS}),
               "referred": dist.categorical({0: 1 - r.referred_share, 1: r.referred_share}),
               # inviters are among the first users, who exist from the start (D91)
               "invited_by": dist.uniform_int(0, n_inviters - 1)},
        refs={"device": std.devices(per_user=dist.categorical({1: .6, 2: .3, 3: .1}),
                                    table=device, share=cfg.household_share_device)})
    p.change_group("address", table="user", cols=("region",))
    p.expose_owner("user")
    # ---------------------------------------------------------------- orders (created owners)
    order = p.table("order", key="order_id", mutable=True, doc="A placed order", cols={
        "user_id": ref("user"), "amount": amount(asset="USD"), "lines": i16(),
        "category": cat(*CATEGORIES), "credit_used": amount(asset="USD"),
        "refunded": amount(asset="USD"),
        "status": cat("placed", "shipped", "delivered", "lost", "returned")})
    p.owner("order", table=order, max_live=max(1_000, int(cfg.users * cfg.orders_live_ratio)))
    # ---------------------------------------------------------------- inventory
    inventory = p.shard("inventory", key="sku_group", n=cfg.sku_groups, items=sku,
                        doc="Stock per inventory group",
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
    # ---------------------------------------------------------------- referral pool
    period_us = parse_duration(r.period)
    pool = p.shard("referral_pool", key="pool_id", n=1, items=None,
                   doc="The referral budget; claims are whole or rejected; reset each period",
                   state={"remaining": "i64", "granted": "i64", "window": "i64"},
                   init={"remaining": [r.monthly_budget], "granted": [0], "window": [-1]})
    usd = amount(asset="USD")
    claim = p.request("claim", frm="user", to=pool,
                      payload={"claim_id": ref("claim"), "amount": usd},
                      response_payload={"claim_id": ref("claim"), "amount": usd},
                      responses=("granted", "rejected"),
                      latency=dist.shifted_lognormal(min_ms=300, median_ms=450))
    # gives back a grant that arrived after a machine's request timeout (D67, F-35)
    p.message("claim_refund", frm="user", to=pool,
              payload={"claim_id": ref("claim"), "amount": usd},
              latency=dist.shifted_lognormal(min_ms=300, median_ms=450))
    inviter_credit = p.message("inviter_credit", frm="user", to="user",
                               payload={"invitee": ref("user"), "amount": usd},
                               latency=dist.shifted_lognormal(min_ms=86_400_000,
                                                              median_ms=100_000_000))
    # ---------------------------------------------------------------- events
    u = {"user_id": ref("user")}
    p.event("user_signed_up", owner="user", doc="A shopper creates an account", cols={
        **u, "device_id": ref("device"), "acquisition": cat(*ACQUISITION),
        "referred": boolean(), "invited_by": opt(ref("user"))})
    p.event("session_started", owner="user", cols={
        **u, "session_id": ref("session"), "device_id": ref("device"), "channel": cat(*CHANNELS)})
    p.event("product_viewed", owner="user", cols={
        **u, "session_id": ref("session"), "sku_id": ref("sku"), "device_id": ref("device"),
        "position": i16(), "category": cat(*CATEGORIES), "price": usd})
    p.event("cart_item_added", owner="user", cols={
        **u, "session_id": ref("session"), "sku_id": ref("sku"), "quantity": i16(),
        "unit_price": usd})
    p.event("checkout_started", owner="user", doc="Credit held; one reserve per cart line",
            cols={**u, "session_id": ref("session"), "checkout_id": ref("checkout"),
                  "lines": i16(), "subtotal": usd, "credit_applied": usd})
    p.event("checkout_failed", owner="user", cols={
        **u, "checkout_id": ref("checkout"), "reason": cat("out_of_stock", "payment_declined"),
        "sku_id": opt(ref("sku"))})
    p.event("payment_authorized", owner="user", cols={
        **u, "checkout_id": ref("checkout"), "amount": usd,
        "method": cat("card", "wallet", "bnpl")})
    p.event("payment_failed", owner="user", cols={
        **u, "checkout_id": ref("checkout"), "amount": usd,
        "decline_code": cat("insufficient_funds", "do_not_honor", "expired_card",
                            "fraud_suspected")})
    p.event("order_placed", owner="user", doc="Stock committed and payment authorized", cols={
        **u, "order_id": ref("order"), "checkout_id": ref("checkout"),
        "device_id": ref("device"), "sku_id": ref("sku"), "lines": i16(), "amount": usd,
        "credit_used": usd, "category": cat(*CATEGORIES)})          # largest line
    p.event("referral_bonus_paid", owner="user", cols={
        **u, "invitee_id": ref("user"), "role": cat("inviter", "invitee"), "amount": usd})
    p.event("referral_bonus_rejected", owner="user", cols={
        **u, "reason": cat("budget_exhausted")})
    o = {"user_id": ref("user"), "order_id": ref("order")}
    p.event("order_shipped", owner="order", cols={**o, "carrier": cat(*CARRIERS)})
    p.event("order_delivered", owner="order", cols={**o, "category": cat(*CATEGORIES)})
    p.event("order_lost", owner="order", cols=o)
    p.event("return_requested", owner="order", cols={**o, "reason": cat(*RETURN_REASONS)})
    p.event("refund_issued", owner="order", cols={**o, "amount": usd})
    stock = {"sku_group": i16(), "sku_id": ref("sku"), "checkout_id": ref("checkout")}
    p.event("stock_reserved", shard="inventory", cols={**stock, "hold_id": ref("hold"),
                                                       "quantity": i16()})
    p.event("stock_rejected", shard="inventory", cols={
        **stock, "quantity": i16(), "reason": cat("out_of_stock", "busy")})
    p.event("stock_committed", shard="inventory", cols={
        **stock, "hold_id": ref("hold"), "quantity": i16(), "on_hand_after": i32()})
    for name in ("stock_released", "stock_expired", "stock_commit_late"):
        p.event(name, shard="inventory", cols={**stock, "hold_id": ref("hold"),
                                               "quantity": i16()})
    p.event("restocked", shard="inventory", doc="Supplier delivery to an inventory group", cols={
        "sku_group": i16(), "sku_id": ref("sku"), "quantity": i32(min=1), "on_hand_after": i32()})
    p.event("bonus_granted", shard="referral_pool", cols={
        "claim_id": ref("claim"), "amount": usd, "remaining_after": i64()})
    p.event("bonus_rejected", shard="referral_pool", cols={"claim_id": ref("claim"),
                                                           "amount": usd})
    p.event("bonus_refunded", shard="referral_pool", doc="A late grant given back; the period's"
            " budget is not reopened", cols={"claim_id": ref("claim"), "amount": usd})
    # ---------------------------------------------------------------- processes
    p.process("shopper", owner="user", kernel=k.shopper, config=cfg,
              start=p.on_created("user"),
              requests={"reserve": reserve, "claim": claim},
              messages={"commit": commit, "release": release, "inviter_credit": inviter_credit},
              on_response={("reserve", "granted"): k.R_GRANTED,
                           ("reserve", "rejected"): k.R_REJECTED,
                           ("claim", "granted"): k.R_BONUS, ("claim", "rejected"): k.R_NO_BONUS},
              on_message={"inviter_credit": k.M_CREDIT},
              reads={"sku": sku, "device": device}, refs={"device": "device"},
              commands=k.SHOPPER_COMMANDS)
    p.process("inventory_desk", shard=inventory, kernel=k.inventory_desk, config=cfg.desk,
              on_request={"reserve": k.C_RESERVE},
              on_message={"commit": k.C_COMMIT, "release": k.C_RELEASE},
              reads={"sku": sku}, commands=k.DESK_COMMANDS)
    p.process("restock", shard=inventory, kernel=k.restock, every=cfg.restock_period,
              jitter=dist.normal(mean_h=0, sd_h=18), reads={"sku": sku})
    p.process("pool_desk", shard=pool, kernel=k.pool_desk,
              config=PoolCfg(budget=r.monthly_budget, period_us=period_us),
              on_request={"claim": k.C_CLAIM}, on_message={"claim_refund": k.C_REFUND},
              commands=(k.C_CLAIM, k.C_REFUND))
    # ---------------------------------------------------------------- fulfillment (a machine)
    fc = cfg.fulfil
    f = p.machine("fulfillment", owner="order", start=p.on_created("order"), initial="placed",
                  config=fc)
    f.state("placed", branch={
        "shipped": (fc.ship_p, dist.gamma(mean_days=1.8, shape=2.0), k.ship),
        "lost": (None, dist.gamma(mean_days=14, shape=4.0), k.lose)})
    f.state("shipped", branch={
        "delivered": (1.0, dist.gamma(mean_days=3.6, shape=3.0), k.deliver)})
    f.state("delivered", branch={
        "returning": (std.p_by("category", {"apparel": fc.return_apparel_p,
                                            "shoes": fc.return_shoes_p},
                               otherwise=fc.return_p),
                      dist.gamma(mean_days=9, shape=1.6, max_days=30), k.request_return),
        "kept": (None, None, None)})
    f.state("returning", branch={
        "returned": (1.0, dist.gamma(mean_days=6, shape=2.5), k.refund_return)})
    f.final("kept", "returned", "lost")
    # ---------------------------------------------------------------- laws (§11)
    p.check("chk.stock_never_negative", law.never_negative("inventory.on_hand"), required=True)
    p.check("chk.reserved_never_negative", law.never_negative("inventory.reserved"),
            required=True)
    p.check("chk.holds_resolved", law.resolved(
        "stock_reserved", by=("stock_committed", "stock_released", "stock_expired"),
        key="hold_id", within=f"{cfg.desk.hold_ttl_s + HOLD_SLACK_S}s"), required=True)
    p.check("chk.refund_le_paid",
            law.sum_le("refund_issued.amount", "order.amount", by="order_id"), required=True)
    p.check("chk.order_lifecycle", law.lifecycle("order_id", edges={
        "order_placed": ("order_shipped", "order_lost"),
        "order_shipped": ("order_delivered",),
        "order_delivered": ("return_requested",),
        "return_requested": ("refund_issued",)}), required=True)
    p.check("chk.referral_once_per_invitee",
            law.at_most_once("referral_bonus_paid", key=("invitee_id", "role")), required=True)
    p.check("chk.referral_budget",
            law.total_le("bonus_granted.amount", r.monthly_budget, per=r.period), required=True)
    p.check("chk.credit_never_negative", law.never_negative("user.credit"), required=True)
    p.check("chk.hold_never_negative", law.never_negative("user.held"), required=True)
    p.check("chk.pool_never_negative", law.never_negative("referral_pool.remaining"),
            required=True)
    # ---------------------------------------------------------------- extension points (§08)
    p.expose(signup=k.signup, signup_invited=k.signup_invited, quick_order=k.quick_order,
             pay_referral=k.pay_referral,
             claim_bonus=std.request(
                 "claim", claim_id=std.new_id("claim"), amount=2 * r.bonus_each,
                 store={"amount": "paid", "claim_id": "claim"},
                 release=std.send("claim_refund", claim_id=std.field("claim"),
                                  amount=std.field("paid"))))
    p.expose_param("referral.min_order", r.min_order)
