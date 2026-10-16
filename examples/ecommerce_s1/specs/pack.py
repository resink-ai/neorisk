"""E-commerce S1 slice (spec §18 S1).

Shoppers browse in sessions, keep a one-line cart, and check out a single SKU against the
inventory shard that owns it. Everything is a handwritten kernel; state machines, multi-SKU
reservations, referrals and overlays arrive with examples/ecommerce at M3.

Partitions
    owner  user        one shopper: profile, cart scratch, checkout in flight
    shard  inventory   one inventory group: on_hand and reserved per SKU

Cross-device KYC (D28): a desktop session shows a handoff token, the shopper scans it on a
phone before it expires (300 s), then a face check completes KYC (change group `user_kyc`).

Boundaries (immutable, latency >= delta)
    user -> inventory  reserve (request, answered granted/rejected)   delta 150 ms
    user -> inventory  commit, release (one-way messages)             delta 150 ms
"""

from dataclasses import dataclass, field

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import amount, boolean, cat, i16, i32, opt, ref, ts

from . import kernels as k

PACK = "ecommerce_s1"
SCHEMA_VERSION = 1

CATEGORIES = (
    "apparel", "shoes", "beauty", "home", "kitchen", "garden", "toys", "baby", "books",
    "music", "video_games", "electronics", "phones", "computers", "office", "pets", "sports",
    "outdoors", "auto", "tools", "grocery", "health", "jewelry", "luggage",
)
CHANNELS = ("web", "app")
ACQUISITION = ("organic", "search_ad", "social_ad", "affiliate")
SOURCES = ("home", "search", "category", "recommendation")
REFERRERS = ("none", "email", "social", "ads")


@dataclass(frozen=True)
class Journey:
    """Shopper behavior; consumed by kernels.shopper."""
    signup_delay: dist.Dist = dist.exp(mean_s=3600)
    session_gap_alpha: float = 1.2          # Pareto tail of gaps between sessions
    session_gap_min_h: float = 30.0
    views_mean: float = 6.0                 # geometric views per session
    view_gap: dist.Dist = dist.exp(mean_s=40)
    add_to_cart_p: float = 0.18             # per view; replaces the one cart line (S1)
    checkout_p: float = 0.35                # per session end with a non-empty cart
    checkout_delay: dist.Dist = dist.exp(mean_s=25)
    substitute_p: float = 0.45              # after out-of-stock: browse for a substitute
    auth_fail_p: float = 0.03
    auth_latency: dist.Dist = dist.lognormal(median_s=2.5, sigma=0.6)
    kyc_start_p: float = 0.05               # per eligible desktop session (D28)
    kyc_expiry_s: int = 300                 # handoff token lifetime
    kyc_redeem_delay: dist.Dist = dist.lognormal(median_s=90, sigma=0.8)
    kyc_late_scan_p: float = 0.02           # scan lands exactly at expiry (counts as expired)
    kyc_duplicate_p: float = 0.03           # the phone scans the same token twice
    kyc_duplicate_gap: dist.Dist = dist.exp(mean_s=20)
    kyc_face_delay: dist.Dist = dist.lognormal(median_s=40, sigma=0.5)


@dataclass(frozen=True)
class Config:
    users: int = 20_000                     # population at the end of the span
    initial_share: float = 0.6
    skus: int = 5_000
    sku_groups: int = 64                    # inventory shards
    restock_period: str = "7d"
    household_share_device: float = 0.12
    journey: Journey = field(default_factory=Journey)


def define(p: Pack, cfg: Config) -> None:
    sku = p.table("sku", key="sku_id", doc="Catalog, fixed for the run", cols={
        "category": cat(*CATEGORIES), "price": amount(asset="USD"), "sku_group": i16()},
        source=std.catalog(n=cfg.skus, category=dist.categorical(
            {c: 1 / len(CATEGORIES) for c in CATEGORIES}),
            price=dist.lognormal_minor(median=2_500, sigma=0.9, min=199, max=200_000),
            group=dist.uniform_int(0, cfg.sku_groups - 1), weight=dist.zipf(s=1.07)))
    device = p.table("device", key="device_id", doc="Shopper devices", cols={
        "os": cat("ios", "android", "windows", "macos", "linux"),
        "kind": cat("phone", "tablet", "desktop"), "first_seen": ts()})
    user = p.table("user", key="user_id", mutable=True, doc="A shopper", cols={
        "age_band": cat("18-24", "25-34", "35-44", "45-54", "55+"),
        "acquisition": cat(*ACQUISITION), "status": cat("active", "dormant"),
        "kyc_level": i16(), "kyc_device": opt(ref("device"))})
    p.table("order", key="order_id", mutable=True, child_of="user", cols={
        "sku_id": ref("sku"), "quantity": i16(), "amount": amount(asset="USD")})
    p.ids("session", "checkout", "flow")
    p.change_group("user_kyc", table="user", cols=["kyc_level", "kyc_device"])

    p.owner("user", table=user, max_live=cfg.users, retire_when_idle=False)
    p.population(
        user, n=cfg.users, initial=cfg.initial_share,
        arrivals=dist.poisson_daily(weekly=(1.0, 0.95, 0.95, 1.0, 1.1, 1.3, 1.25), trend=0.002),
        attrs={"age_band": dist.categorical({"18-24": .17, "25-34": .31, "35-44": .24,
                                             "45-54": .16, "55+": .12}),
               "acquisition": dist.categorical({"organic": .55, "search_ad": .2,
                                                "social_ad": .15, "affiliate": .1})},
        refs={"device": std.devices(per_user=dist.categorical({1: .6, 2: .3, 3: .1}),
                                    table=device, share=cfg.household_share_device)})

    inventory = p.shard("inventory", key="sku_group", n=cfg.sku_groups, items=sku,
                        doc="Stock per inventory group",
                        state={"on_hand": "i32[sku]", "reserved": "i32[sku]"},
                        init=std.stock(initial=dist.negbinom(mean=40, disp=0.7), by_weight=8.0))
    lat = dist.shifted_lognormal(min_ms=150, median_ms=240)
    line = {"sku_id": ref("sku"), "quantity": i16()}
    reserve = p.request("reserve", frm="user", to=inventory, payload=line,
                        responses=("granted", "rejected"), latency=lat)
    commit = p.message("commit", frm="user", to=inventory, payload=line, latency=lat)
    release = p.message("release", frm="user", to=inventory, payload=line, latency=lat)

    u = {"user_id": ref("user")}
    p.event("user_signed_up", owner="user", doc="A shopper creates an account", cols={
        **u, "device_id": ref("device"), "acquisition": cat(*ACQUISITION),
        "age_band": cat("18-24", "25-34", "35-44", "45-54", "55+")})
    p.event("session_started", owner="user", cols={
        **u, "session_id": ref("session"), "device_id": ref("device"), "channel": cat(*CHANNELS)})
    p.event("product_viewed", owner="user", doc="12 property columns (S1 benchmark shape)", cols={
        **u, "session_id": ref("session"), "sku_id": ref("sku"), "device_id": ref("device"),
        "position": i16(), "source": cat(*SOURCES), "channel": cat(*CHANNELS),
        "category": cat(*CATEGORIES), "price": amount(asset="USD"), "page_ms": i32(min=0),
        "referrer": cat(*REFERRERS), "is_recommended": boolean()})
    p.event("cart_item_added", owner="user", cols={
        **u, "session_id": ref("session"), "sku_id": ref("sku"), "quantity": i16(),
        "unit_price": amount(asset="USD")})
    p.event("checkout_started", owner="user", cols={
        **u, "session_id": ref("session"), "checkout_id": ref("checkout"), "sku_id": ref("sku"),
        "quantity": i16(), "subtotal": amount(asset="USD")})
    p.event("checkout_failed", owner="user", cols={
        **u, "checkout_id": ref("checkout"), "reason": cat("out_of_stock", "payment_declined"),
        "sku_id": opt(ref("sku"))})
    p.event("payment_authorized", owner="user", cols={
        **u, "checkout_id": ref("checkout"), "amount": amount(asset="USD"),
        "method": cat("card", "wallet", "bnpl")})
    p.event("payment_failed", owner="user", cols={
        **u, "checkout_id": ref("checkout"), "amount": amount(asset="USD"),
        "decline_code": cat("insufficient_funds", "do_not_honor", "expired_card",
                            "fraud_suspected")})
    p.event("order_placed", owner="user", doc="Stock committed and payment authorized", cols={
        **u, "order_id": ref("order"), "checkout_id": ref("checkout"), "device_id": ref("device"),
        "sku_id": ref("sku"), "quantity": i16(), "amount": amount(asset="USD"),
        "category": cat(*CATEGORIES)})
    p.event("kyc_started", owner="user", doc="A desktop session shows a KYC handoff token",
            cols={**u, "flow_id": ref("flow"), "session_id": ref("session"),
                  "device_id": ref("device"), "expires_at": ts()})
    p.event("kyc_handoff_redeemed", owner="user", doc="The token was scanned on the phone",
            cols={**u, "flow_id": ref("flow"), "device_id": ref("device")})
    p.event("kyc_handoff_rejected", owner="user", doc="A scan of an expired or used token",
            cols={**u, "flow_id": ref("flow"), "device_id": ref("device"),
                  "reason": cat("expired", "already_redeemed")})
    p.event("kyc_handoff_expired", owner="user", cols={**u, "flow_id": ref("flow")})
    p.event("kyc_completed", owner="user", doc="Face check passed; back on the desktop session",
            cols={**u, "flow_id": ref("flow"), "session_id": ref("session"),
                  "device_id": ref("device"), "scan_device_id": ref("device")})
    stock_cols = {"sku_group": i16(), "sku_id": ref("sku"), "checkout_id": ref("checkout"),
                  "quantity": i16()}
    p.event("stock_reserved", shard="inventory", cols=stock_cols)
    p.event("stock_rejected", shard="inventory", cols=stock_cols)
    p.event("stock_committed", shard="inventory", cols={**stock_cols, "on_hand_after": i32()})
    p.event("stock_released", shard="inventory", cols=stock_cols)
    p.event("restocked", shard="inventory", doc="Supplier delivery to an inventory group", cols={
        "sku_group": i16(), "sku_id": ref("sku"), "quantity": i32(min=1), "on_hand_after": i32()})

    p.process("shopper", owner="user", kernel=k.shopper, config=cfg.journey,
              start=p.on_created("user"), requests={"reserve": reserve},
              messages={"commit": commit, "release": release},
              on_response={("reserve", "granted"): k.R_GRANTED,
                           ("reserve", "rejected"): k.R_REJECTED},
              reads={"sku": sku, "device": device}, refs={"device": "device"},
              commands=k.SHOPPER_COMMANDS)
    p.process("inventory_desk", shard=inventory, kernel=k.inventory_desk,
              on_request={"reserve": k.C_RESERVE},
              on_message={"commit": k.C_COMMIT, "release": k.C_RELEASE}, reads={"sku": sku})
    p.process("restock", shard=inventory, kernel=k.restock, every=cfg.restock_period,
              jitter=dist.normal(mean_h=0, sd_h=18), reads={"sku": sku})

    p.check("chk.stock_never_negative", std.law.never_negative("inventory.on_hand"),
            required=True)
