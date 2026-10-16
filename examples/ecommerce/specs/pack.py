"""E-commerce marketplace pack.

Partitions
    owner  user           one shopper with their orders, cart, credit and processes
    shard  inventory      one inventory group (warehouse zone): stock for its SKUs
    shard  referral_pool  the referral program's monthly budget

Boundaries (immutable request/response, latency >= delta)
    user -> inventory      reserve / commit / release stock         delta 150 ms
    user -> referral_pool  claim a referral bonus                   delta 300 ms
    user -> user           inviter credit, delivered next step or later
"""

from dataclasses import dataclass, field

from neorisk_simkit.spec import Pack, dist, law, std
from neorisk_simkit.spec.types import amount, boolean, cat, i16, i32, opt, ref, text, ts

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


# --------------------------------------------------------------------------- config
@dataclass(frozen=True)
class Journey:
    """Shopper behavior; consumed by kernels.shopper_journey."""
    session_gap_alpha: float = 1.2          # Pareto tail of gaps between sessions
    session_gap_min_h: float = 6.0
    views_mean: float = 6.0                 # geometric views per session
    add_to_cart_p: float = 0.18             # per view
    checkout_p: float = 0.08                # per session with a non-empty cart
    substitute_p: float = 0.45              # after out-of-stock: try a substitute
    auth_fail_p: float = 0.03
    auth_latency: dist.Dist = dist.lognormal(median_s=2.5, sigma=0.6)
    credit_use_p: float = 0.9               # use available credit at checkout
    max_cart_lines: int = 5


@dataclass(frozen=True)
class Referral:
    inviter_p: float = 0.04
    invites: dist.Dist = dist.geometric(mean=2.0, max=5)
    invite_signup_p: float = 0.35
    signup_delay: dist.Dist = dist.gamma(mean_days=2.0, shape=1.5, max_days=7)
    min_order: int = 3_000                  # cents
    bonus_each: int = 1_000                 # cents; inviter and invitee
    monthly_budget: int = 25_000_000        # cents
    qualify_window: str = "30d"


@dataclass(frozen=True)
class Config:
    users: int = 200_000                    # population at the end of the span
    initial_share: float = 0.6              # share that exists at the start
    skus: int = 50_000
    sku_groups: int = 512                   # inventory shards
    restock_period: str = "7d"
    household_share_device: float = 0.12
    journey: Journey = field(default_factory=Journey)
    referral: Referral = field(default_factory=Referral)
    execution_owner: str = "user_id"        # overlays may group cohort members under another owner


# --------------------------------------------------------------------------- pack
def define(p: Pack, cfg: Config) -> None:
    j, r = cfg.journey, cfg.referral

    # ---------------------------------------------------------------- read inputs
    sku = p.table("sku", key="sku_id", mutable=False, doc="Catalog, fixed for the run", cols={
        "category": cat(*CATEGORIES),
        "price": amount(asset="USD"),
        "sku_group": i16(),
        "popularity": cat("head", "torso", "tail"),
    }, source=std.catalog(
        n=cfg.skus,
        category=dist.categorical_zipf(CATEGORIES, s=0.8),
        price=dist.lognormal_minor(median=2_500, sigma=0.9, min=199, max=200_000),
        group=dist.uniform_int(0, cfg.sku_groups - 1),
        weight=dist.zipf(s=1.07),           # view propensity; top 1% ~ 20% of views
    ))

    device = p.table("device", key="device_id", mutable=False, doc="Shopper devices", cols={
        "os": cat("ios", "android", "windows", "macos", "linux"),
        "kind": cat("phone", "tablet", "desktop"),
        "first_seen": ts(),
    })

    # ---------------------------------------------------------------- owner state
    user = p.table("user", key="user_id", mutable=True, doc="A shopper and their wallet", cols={
        "signup_at": ts(),
        "age_band": cat("18-24", "25-34", "35-44", "45-54", "55+"),
        "acquisition": cat(*ACQUISITION),
        "invited_by": opt(ref("user")),
        "credit": amount(asset="USD"),      # referral credit balance
        "credit_hold": amount(asset="USD"),
        "status": cat("active", "dormant", "closed"),
        "first_paid_order": opt(ref("order")),
    })
    order = p.table("order", key="order_id", mutable=True, child_of="user", cols={
        "lines": i16(), "amount": amount(asset="USD"), "credit_used": amount(asset="USD"),
        "refunded": amount(asset="USD"), "status": cat("placed", "shipped", "delivered", "lost",
                                                      "returned"),
    })

    # ID namespaces without a table of their own (minted by out.new_id in kernels)
    p.ids("session", "checkout", "invite", "reservation")

    p.owner("user", table="user", execution_owner=cfg.execution_owner, max_live=cfg.users,
            children=["order"])

    p.population(
        user, n=cfg.users,
        initial=cfg.initial_share,
        arrivals=dist.poisson_daily(weekly=(1.0, 0.95, 0.95, 1.0, 1.1, 1.3, 1.25),
                                    trend=0.002),
        attrs={
            "age_band": dist.categorical({"18-24": .17, "25-34": .31, "35-44": .24,
                                          "45-54": .16, "55+": .12}),
            "acquisition": dist.categorical({"organic": .55, "search_ad": .2,
                                             "social_ad": .15, "affiliate": .1}),
        },
        refs={"device": std.devices(per_user=dist.categorical({1: .6, 2: .3, 3: .1}),
                                    table=device, share=cfg.household_share_device)},
    )

    # ---------------------------------------------------------------- shards
    inventory = p.shard("inventory", key="sku_group", n=cfg.sku_groups, doc="Stock per group",
                        state={"on_hand": "i32[sku]", "reserved": "i32[sku]"},
                        init=std.stock(initial=dist.negbinom(mean=40, disp=0.7),
                                       by_popularity={"head": 8.0, "torso": 2.0, "tail": 1.0}))

    pool = std.capped_pool(p, "referral_pool", budget=r.monthly_budget, period="calendar_month",
                           frm="user",
                           latency=dist.shifted_lognormal(min_ms=300, median_ms=450))

    stock = std.reservations(
        p, "stock", frm="user", shard=inventory, item="sku_id", qty="quantity",
        available=lambda s, item: s.on_hand[item] - s.reserved[item],
        ttl="10m",
        latency=dist.shifted_lognormal(min_ms=150, median_ms=240),
        emits=("stock_reserved", "stock_rejected", "stock_committed", "stock_released",
               "stock_expired"),
    )

    p.process("restock", shard=inventory, kernel=k.restock,
              every=cfg.restock_period, jitter=dist.normal(mean_h=0, sd_h=18))

    # ---------------------------------------------------------------- events
    common_user = {"user_id": ref("user")}
    p.event("user_signed_up", owner="user", doc="A shopper creates an account", cols={
        **common_user, "acquisition": cat(*ACQUISITION), "device_id": ref("device"),
        "invite_id": opt(ref("invite")),
    })
    p.event("session_started", owner="user", cols={
        **common_user, "session_id": ref("session"), "device_id": ref("device"),
        "channel": cat(*CHANNELS),
    })
    p.event("product_viewed", owner="user", cols={
        **common_user, "session_id": ref("session"), "sku_id": ref("sku"),
        "position": i16(), "source": cat("home", "search", "category", "recommendation"),
    })
    p.event("cart_item_added", owner="user", cols={
        **common_user, "session_id": ref("session"), "sku_id": ref("sku"), "quantity": i16(),
        "unit_price": amount(asset="USD"),
    })
    p.event("checkout_started", owner="user", cols={
        **common_user, "session_id": ref("session"), "checkout_id": ref("checkout"),
        "lines": i16(), "subtotal": amount(asset="USD"), "credit_applied": amount(asset="USD"),
    })
    p.event("checkout_failed", owner="user", cols={
        **common_user, "checkout_id": ref("checkout"),
        "reason": cat("out_of_stock", "payment_declined", "timeout", "abandoned"),
        "sku_id": opt(ref("sku")),
    })
    p.event("payment_authorized", owner="user", cols={
        **common_user, "checkout_id": ref("checkout"), "amount": amount(asset="USD"),
        "method": cat("card", "wallet", "bnpl"),
    })
    p.event("payment_failed", owner="user", cols={
        **common_user, "checkout_id": ref("checkout"), "amount": amount(asset="USD"),
        "decline_code": cat("insufficient_funds", "do_not_honor", "expired_card", "fraud_suspected"),
    })
    p.event("order_placed", owner="user", doc="Stock committed and payment authorized", cols={
        **common_user, "order_id": ref("order"), "checkout_id": ref("checkout"),
        "device_id": ref("device"), "lines": i16(), "amount": amount(asset="USD"),
        "credit_used": amount(asset="USD"), "category": cat(*CATEGORIES),  # largest line
    })
    p.event("order_shipped", owner="user", cols={**common_user, "order_id": ref("order"),
                                                 "carrier": cat("ups", "fedex", "usps", "dhl")})
    p.event("order_delivered", owner="user", cols={**common_user, "order_id": ref("order")})
    p.event("order_lost", owner="user", cols={**common_user, "order_id": ref("order")})
    p.event("return_requested", owner="user", cols={
        **common_user, "order_id": ref("order"), "lines": i16(),
        "reason": cat("size", "damaged", "not_as_described", "changed_mind", "late"),
    })
    p.event("refund_issued", owner="user", cols={
        **common_user, "order_id": ref("order"), "amount": amount(asset="USD"),
    })
    p.event("invite_sent", owner="user", cols={
        **common_user, "invite_id": ref("invite"), "medium": cat("link", "email", "sms"),
    })
    p.event("referral_bonus_paid", owner="user", cols={
        **common_user, "invitee_id": ref("user"), "role": cat("inviter", "invitee"),
        "amount": amount(asset="USD"),
    })
    p.event("referral_bonus_rejected", owner="user", cols={
        **common_user, "invitee_id": ref("user"), "reason": cat("budget_exhausted", "duplicate"),
    })
    p.event("restocked", shard="inventory", doc="Supplier delivery to an inventory group", cols={
        "sku_group": i16(), "sku_id": ref("sku"), "quantity": i32(min=1),
    })
    # stock_* events are declared by std.reservations; pool_claim_* events by std.capped_pool

    # ---------------------------------------------------------------- processes
    p.process("shopper_journey", owner="user", kernel=k.shopper_journey, config=j,
              start=p.on_created("user"),
              requests={"reserve": stock.reserve, "commit": stock.commit, "release": stock.release},
              reads={"sku": sku, "device": device},
              commands=k.JOURNEY_COMMANDS)

    # Fulfillment and returns: common behavior, so a state machine
    f = p.machine("fulfillment", owner="user", instance="order", start=p.on_event("order_placed"),
                  initial="placed")
    f.state("placed", branch={
        "shipped": (0.985, dist.gamma(mean_days=1.8, shape=2.0), std.emit("order_shipped")),
        "lost":    (0.015, dist.gamma(mean_days=14, shape=4.0), std.emit("order_lost")),
    })
    f.state("shipped", branch={
        "delivered": (1.0, dist.gamma(mean_days=3.6, shape=3.0), std.emit("order_delivered")),
    })
    f.state("delivered", branch={
        "returning": (std.by_category({"apparel": 0.18, "shoes": 0.14, "otherwise": 0.045}),
                      dist.gamma(mean_days=9, shape=1.6, max_days=30),
                      std.emit("return_requested", lines=std.return_lines())),
        "otherwise": (None, None, None),    # unpicked mass
    })
    f.state("returning", branch={
        "returned": (1.0, dist.gamma(mean_days=6, shape=2.5), k.refund_return),
    })
    f.final("returned", "lost", "otherwise")

    # Referral: inviter side
    inv = p.machine("inviter", owner="user", start=p.on_event("order_placed", first=True),
                    initial="maybe")
    inv.state("maybe", branch={
        "inviting": (r.inviter_p, dist.exp(mean_days=5), None),
        "otherwise": (1 - r.inviter_p, None, None),
    })
    inv.state("inviting", repeat=(dist.exp(mean_days=2), 1.0,
                                  std.emit("invite_sent", medium=dist.categorical(
                                      {"link": .6, "email": .25, "sms": .15}))
                                  .then(std.maybe_create_owner(
                                      "user", p=r.invite_signup_p, delay=r.signup_delay,
                                      attrs={"acquisition": "invite"},
                                      link={"invited_by": "self", "invite_id": "last_invite"}))),
              max_repeats=r.invites, then="done")
    inv.on_message("inviter_credit", k.credit_inviter)   # owner-to-owner, next step or later

    # Referral: invitee side, started for users created through an invite
    ivt = p.machine("invitee", owner="user", start=p.on_created("user", where="acquisition == 'invite'"),
                    initial="waiting")
    ivt.state("waiting", until=std.first_paid_order(min_amount=r.min_order), then="claiming",
              timer={"expired": r.qualify_window})
    ivt.state("claiming", request={"granted": pool.claim(amount=2 * r.bonus_each)},
              on_reject="rejected", timeout="1m")
    ivt.state("granted", branch={"done": (1.0, None, k.pay_invitee_bonus.then(
        std.send_owner("inviter_credit", to="invited_by", payload={"amount": r.bonus_each})))})
    ivt.state("rejected", branch={"done": (1.0, None, std.emit("referral_bonus_rejected",
                                                               reason="budget_exhausted"))})
    ivt.final("done", "expired")

    # ---------------------------------------------------------------- enrichment
    # Cross-owner feature, computed after each step seals on canonical order; goes to golden/
    p.feature("device_distinct_users_24h",
              std.rolling_distinct("user_id", by="device_id", window="24h"),
              on=["order_placed", "user_signed_up"], into="golden")
    p.feature("user_orders_7d", std.rolling_count("order_placed", by="user_id", window="7d"),
              on=["order_placed"], into="golden")

    # ---------------------------------------------------------------- laws
    p.check("chk.stock_never_negative", law.never_negative("inventory.on_hand"), required=True)
    p.check("chk.reservation_resolved",
            law.resolved("stock_reserved", by=("stock_committed", "stock_released", "stock_expired"),
                         key="reservation_id", within="ttl"), required=True)
    p.check("chk.refund_le_paid",
            law.sum_le("refund_issued.amount", "order_placed.amount", by="order_id"), required=True)
    p.check("chk.order_lifecycle", law.lifecycle("order_id", edges={
        "order_placed": ("order_shipped", "order_lost"),
        "order_shipped": ("order_delivered",),
        "order_delivered": ("return_requested",),
        "return_requested": ("refund_issued",),
    }), required=True)
    p.check("chk.referral_once_per_invitee",
            law.at_most_once("referral_bonus_paid", key=("invitee_id", "role")), required=True)
    p.check("chk.referral_budget",
            law.sum_le_cap("referral_bonus_paid.amount", cap=r.monthly_budget,
                           per="calendar_month"), required=True)
    p.check("chk.credit_never_negative", law.never_negative("user.credit"), required=True)

    # ---------------------------------------------------------------- extension points
    # Named actions overlays may call (validate checks them against the resolved plan)
    p.expose(
        signup=k.signup, signup_via_invite=k.signup_via_invite, invite=k.send_invite,
        first_order=k.quick_order, claim_invitee_bonus=pool.claim(amount=2 * r.bonus_each),
        claim_inviter_bonus=k.credit_inviter, session=k.start_session,
    )
    p.expose_param("referral.min_order", r.min_order)
