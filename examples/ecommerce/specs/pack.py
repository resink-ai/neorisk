"""E-commerce shoppers with a referral program.

Shoppers sign up, run sessions (view products, sometimes check out), place orders, sometimes
return them, and sometimes move region. A checkout reserves each cart line in the inventory
shard of its SKU group (one hot group holds the most viewed SKUs), joins on the replies, then
commits all or releases all; reservations expire after a TTL. A referred shopper's first qualifying order claims its
inviter's bonus, after a delay, from a monthly budget held by the `referral_pool` shard. The
pool pays (or rejects) and credits the inviter by message.

Extension points for overlays: `signup` (payload `devices` or `n_devices`), `checkout`
(payload `device`, `lines` = [(sku, qty)], optional `amount`) and `bonus_credited` (a no-op
for shoppers).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from neorisk_simkit.checks import laws
from neorisk_simkit.engine import DAY
from neorisk_simkit.spec import Latency, Pack, amount, cat, i32, i64, opt, ref
from neorisk_simkit.std import reservations
from neorisk_simkit.std.pool import CappedPool

NAME = "ecommerce"
SCHEMA_VERSION = 1

AGE_BANDS = ("18-24", "25-34", "35-44", "45-54", "55+")
REGIONS = ("CA", "TX", "NY", "FL", "WA", "IL", "PA", "OH")
CHANNELS = ("organic", "ads", "social", "invite")
OSES = ("ios", "android", "windows", "macos")
DEVICE_KINDS = ("phone", "tablet", "desktop")
CATEGORIES = ("books", "electronics", "home", "fashion", "toys", "grocery")


@dataclass
class Config:
    users: int = 2000
    arrive_share: float = 0.5         # users arrive over this share of the span
    skus: int = 400
    sku_zipf: float = 1.1
    sessions_per_day: float = 0.25
    views_mean: float = 3.0
    checkout_p: float = 0.08
    order_p: float = 0.8              # checkout -> order (the rest abandon or fail payment)
    return_p: float = 0.06
    move_p_per_day: float = 0.002
    second_device_p: float = 0.3
    referred_share: float = 0.3
    min_order_cents: int = 3000
    bonus_cents: int = 1000
    monthly_budget_cents: int = 2_000_000
    credit_delay_days: tuple[float, float] = (1.0, 3.0)
    second_line_p: float = 0.25       # a cart gets a second SKU
    sku_groups: int = 12              # inventory shards; group 0 is the hot one
    hot_skus: int = 10                # the most viewed SKUs, all in group 0
    stock_mean: int = 30              # target units per SKU
    restock_days: float = 1.0         # restock SKUs below a quarter of target this often
    reserve_ttl: float = 600.0


@dataclass
class User:
    uid: int = 0
    region: str = ""
    acquisition: str = ""
    inviter: int | None = None        # the inviter's user id ...
    inviter_pid: int | None = None    # ... and partition
    devices: list[int] = field(default_factory=list)
    claimed: bool = False             # the referral claim has been made
    cart: dict | None = None          # the checkout waiting on inventory replies


@dataclass
class Inventory(reservations.Stock):
    target: dict[int, int] = field(default_factory=dict)   # sku -> restock target


@dataclass
class Pool:
    budget: CappedPool = field(default_factory=lambda: CappedPool(0))


def define(p: Pack) -> None:
    p.entity("users", key="user_id", doc="Shoppers (and overlay actors)", cols={
        "age_band": cat(*AGE_BANDS), "region": cat(*REGIONS, doc="Region at signup"),
        "acquisition": cat(*CHANNELS), "invited_by": opt(ref("users"))})
    p.entity("devices", key="device_id", cols={
        "user_id": ref("users", doc="First owner"), "os": cat(*OSES),
        "kind": cat(*DEVICE_KINDS)})
    p.entity("skus", key="sku_id", cols={"category": cat(*CATEGORIES), "price": amount()})
    p.entity("orders", key="order_id", cols={
        "user_id": ref("users"), "sku_id": ref("skus", doc="First line"),
        "quantity": i32(min=1, doc="First line"), "lines": i32(min=1), "amount": amount()})
    p.entity("order_lines", key="line_id", cols={
        "order_id": ref("orders"), "sku_id": ref("skus"), "quantity": i32(min=1),
        "amount": amount()})

    p.event("user_signed_up", doc="A user creates an account", cols={
        "user_id": ref("users"), "device_id": ref("devices"),
        "invited_by": opt(ref("users")), "acquisition": cat(*CHANNELS)})
    p.event("session_started", cols={
        "user_id": ref("users"), "device_id": ref("devices"), "session_id": i64()})
    p.event("product_viewed", cols={
        "user_id": ref("users"), "device_id": ref("devices"), "session_id": i64(),
        "sku_id": ref("skus")})
    p.event("order_placed", doc="A shopper places an order", cols={
        "user_id": ref("users"), "device_id": ref("devices"), "order_id": ref("orders"),
        "sku_id": ref("skus"), "quantity": i32(min=1), "amount": amount()})
    p.event("checkout_failed", doc="A cart line could not be reserved", cols={
        "user_id": ref("users"), "device_id": ref("devices"),
        "reason": cat("out_of_stock", "timeout")})
    p.event("stock_restocked", cols={"sku_id": ref("skus"), "qty": i32(min=1)})
    p.event("order_returned", cols={
        "user_id": ref("users"), "order_id": ref("orders"), "amount": amount()})
    p.event("address_changed", cols={"user_id": ref("users"), "region": cat(*REGIONS)})
    p.event("referral_bonus_paid", doc="The pool pays an inviter for a qualified invitee", cols={
        "user_id": ref("users", doc="The inviter"), "invitee_id": ref("users"),
        "amount": amount()})
    p.event("referral_bonus_rejected", doc="The monthly budget is exhausted", cols={
        "user_id": ref("users", doc="The inviter"), "invitee_id": ref("users")})

    user = p.owner("user", state=User, latency=Latency(0.05, 0.5))
    pool = p.shard("referral_pool", state=Pool, latency=Latency(0.2, 0.8),
                   doc="Monthly referral budget; every claim goes through it")
    inventory = p.shard("inventory", state=Inventory, latency=Latency(0.1, 0.4),
                        doc="One SKU group's stock")
    reservations.install(p, inventory, item="sku_id", item_ref="skus", ttl=600.0)
    stocking = inventory.process("stocking", start="open_store")
    account = user.process("account", doc="Signup, checkout, orders and referral claims")
    shopper = user.process("shopper", start="arrive", doc="Browsing sessions")

    @account.action
    def signup(ctx, s, cmd):
        cfg, rng = ctx.cfg, ctx.rng
        if not s.uid:                                  # overlay actors: not pre-inserted
            s.region = s.region or REGIONS[rng.integers(len(REGIONS))]
            s.acquisition = s.acquisition or ("invite" if s.inviter else
                                              CHANNELS[rng.integers(len(CHANNELS) - 1)])
            s.uid = ctx.insert("users", age_band=AGE_BANDS[rng.integers(len(AGE_BANDS))],
                               region=s.region, acquisition=s.acquisition,
                               invited_by=s.inviter)
        devices = cmd.payload.get("devices")
        if devices:
            s.devices = list(devices)
        else:
            n = cmd.payload.get("n_devices") or (2 if rng.random() < cfg.second_device_p else 1)
            s.devices = [ctx.insert("devices", user_id=s.uid, os=OSES[rng.integers(len(OSES))],
                                    kind=DEVICE_KINDS[rng.integers(len(DEVICE_KINDS))])
                         for _ in range(n)]
        ctx.emit("user_signed_up", user_id=s.uid, device_id=s.devices[0],
                 invited_by=s.inviter, acquisition=s.acquisition)

    @account.action
    def checkout(ctx, s, cmd):
        if s.cart is not None:
            return ctx.reject("checkout_in_progress")
        group = ctx.shared.catalog.group
        cart = {"device": cmd.device, "lines": list(cmd.lines),
                "amount": cmd.payload.get("amount"), "waiting": {}, "held": [], "bad": None}
        for sku, qty in cart["lines"]:
            req = ctx.request(ctx.find("inventory", int(group[sku - 1])), "reserve",
                              reply="reserved", item=sku, qty=qty, timeout=30.0)
            cart["waiting"][req] = sku
        s.cart = cart

    @account.action
    def reserved(ctx, s, cmd):
        c = s.cart
        del c["waiting"][cmd.req]
        if cmd.ok:
            c["held"].append((cmd.sender, cmd.reservation))
        else:
            c["bad"] = c["bad"] or ("timeout" if cmd.status == "timeout" else "out_of_stock")
        if c["waiting"]:
            return ctx.commit()                        # join: wait for every line
        s.cart = None
        done = "release_reservation" if c["bad"] else "commit_reservation"
        for shard, rid in c["held"]:
            ctx.send(shard, done, reservation=rid)
        if c["bad"]:
            ctx.emit("checkout_failed", user_id=s.uid, device_id=c["device"], reason=c["bad"])
            return ctx.commit()
        ctx.call("place_order", device=c["device"], lines=c["lines"], amount=c["amount"])

    @account.action
    def place_order(ctx, s, cmd):
        cfg, rng, price = ctx.cfg, ctx.rng, ctx.shared.catalog.price
        lines = [(sku, qty, qty * int(price[sku - 1])) for sku, qty in cmd.lines]
        amt = cmd.amount if cmd.amount is not None else sum(a for _, _, a in lines)
        (sku, qty, _) = lines[0]
        oid = ctx.insert("orders", user_id=s.uid, sku_id=sku, quantity=qty, lines=len(lines),
                         amount=amt)
        for k, q, a in lines:
            ctx.insert("order_lines", order_id=oid, sku_id=k, quantity=q, amount=a)
        ctx.emit("order_placed", user_id=s.uid, device_id=cmd.device, order_id=oid,
                 sku_id=sku, quantity=qty, amount=amt)
        if rng.random() < cfg.return_p:
            ctx.after(rng.uniform(1, 20) * DAY, "return_order", order=oid, amount=amt)
        if s.inviter and not s.claimed and amt >= cfg.min_order_cents:
            s.claimed = True
            lo, hi = cfg.credit_delay_days
            ctx.after(rng.uniform(lo, hi) * DAY, "claim_referral")

    @account.action
    def return_order(ctx, s, cmd):
        ctx.emit("order_returned", user_id=s.uid, order_id=cmd.order, amount=cmd.amount)

    @account.action
    def claim_referral(ctx, s, cmd):
        ctx.request(ctx.find("referral_pool", "main"), "claim", reply="claim_answered",
                    inviter=s.inviter, inviter_pid=s.inviter_pid, invitee=s.uid)

    @account.action
    def claim_answered(ctx, s, cmd):
        return ctx.commit()                            # the pool already recorded the outcome

    @account.action
    def bonus_credited(ctx, s, cmd):
        return ctx.commit()                            # extension point: shoppers do nothing

    @pool.action
    def claim(ctx, s, cmd):
        cfg = ctx.cfg
        if not s.budget.take(ctx.now, cfg.bonus_cents):
            ctx.emit("referral_bonus_rejected", user_id=cmd.inviter, invitee_id=cmd.invitee)
            return ctx.decline("budget_exhausted")
        ctx.emit("referral_bonus_paid", user_id=cmd.inviter, invitee_id=cmd.invitee,
                 amount=cfg.bonus_cents)
        ctx.send(cmd.inviter_pid, "bonus_credited", amount=cfg.bonus_cents)
        return ctx.reply(granted=True)

    @shopper.action
    def arrive(ctx, s, cmd):
        ctx.call("signup")
        ctx.call("session")

    @shopper.action
    def session(ctx, s, cmd):
        cfg, rng, cat_ = ctx.cfg, ctx.rng, ctx.shared.catalog
        device = s.devices[rng.integers(len(s.devices))]
        sid = ctx.new_id("session")
        ctx.emit("session_started", user_id=s.uid, device_id=device, session_id=sid)
        n = 1 + rng.poisson(cfg.views_mean - 1)
        viewed = np.searchsorted(cat_.cdf, rng.random(n), side="right") + 1
        for sku in viewed:
            ctx.emit("product_viewed", user_id=s.uid, device_id=device, session_id=sid,
                     sku_id=int(sku))
        if rng.random() < cfg.checkout_p and rng.random() < cfg.order_p:
            lines = [(int(viewed[-1]), 1 + int(rng.poisson(0.3)))]
            other = [int(k) for k in viewed[:-1] if k != viewed[-1]]
            if other and rng.random() < cfg.second_line_p:
                lines.append((other[-1], 1))
            ctx.call("checkout", device=device, lines=lines)
        if rng.random() < cfg.move_p_per_day / max(cfg.sessions_per_day, 1e-9):
            s.region = REGIONS[rng.integers(len(REGIONS))]
            ctx.emit("address_changed", user_id=s.uid, region=s.region)
        ctx.after(rng.exponential(DAY / cfg.sessions_per_day), "session")

    @stocking.action
    def open_store(ctx, s, cmd):
        for sku in sorted(s.target):
            ctx.emit("stock_restocked", sku_id=sku, qty=s.units[sku])
        ctx.after(ctx.cfg.restock_days * DAY, "restock")

    @stocking.action
    def restock(ctx, s, cmd):
        for sku in sorted(s.target):
            if s.units[sku] * 4 < s.target[sku]:
                qty = s.target[sku] - s.units[sku]
                s.units[sku] += qty
                ctx.emit("stock_restocked", sku_id=sku, qty=qty)
        ctx.after(ctx.cfg.restock_days * DAY, "restock")

    p.check("order_lifecycle", laws.lifecycle("order_id", {
        None: {"order_placed"}, "order_placed": {"order_returned"}}))
    p.check("returns_le_order", laws.sum_le(("order_returned", "amount"),
                                            ("order_placed", "amount"), by="order_id"))
    p.check("stock_never_negative", laws.running_nonneg(
        "sku_id", plus=[("stock_restocked", "qty"), ("reservation_released", "qty")],
        minus=[("reservation_granted", "qty")], what="stock"))
    p.check("reservations_resolved_by_ttl", laws.reservations_resolved(), group="cross")
    p.check("one_bonus_per_invitee", laws.unique("referral_bonus_paid", ["invitee_id"]),
            group="cross")
    p.check("monthly_budget", laws.pool_within_cap(
        "referral_bonus_paid", "amount", "cfg.monthly_budget_cents", period_days=30),
        group="cross")

    @p.source
    def population(src):
        cfg, rng = src.cfg, src.rng
        price = np.exp(rng.normal(np.log(2500), 0.8, cfg.skus)).astype(np.int64) + 99
        category = rng.integers(0, len(CATEGORIES), cfg.skus)
        for i in range(cfg.skus):
            src.insert("skus", category=CATEGORIES[category[i]], price=int(price[i]))
        w = 1.0 / np.arange(1, cfg.skus + 1) ** cfg.sku_zipf
        sku = np.arange(1, cfg.skus + 1)
        group = np.where(sku <= cfg.hot_skus, 0, 1 + (sku - 1) % (cfg.sku_groups - 1))
        src.share("catalog", price=price, cdf=np.cumsum(w) / w.sum(), group=group)
        target = 1 + src.rng.poisson(cfg.stock_mean, cfg.skus)
        for g in range(cfg.sku_groups):
            mine = {int(k): int(target[k - 1]) for k in sku[group == g]}
            src.create("inventory", key=g, units=dict(mine), target=mine)
        src.create("referral_pool", key="main",
                   budget=CappedPool(cfg.monthly_budget_cents, period=30 * DAY))
        users: list[tuple[int, int]] = []
        for _ in range(cfg.users):
            t = rng.uniform(0, src.days * cfg.arrive_share) * DAY
            inviter = (users[rng.integers(len(users))]
                       if users and rng.random() < cfg.referred_share else None)
            region = REGIONS[rng.integers(len(REGIONS))]
            acq = "invite" if inviter else CHANNELS[rng.integers(len(CHANNELS) - 1)]
            age = AGE_BANDS[rng.integers(len(AGE_BANDS))]
            if t >= src.horizon:
                continue
            uid = src.insert("users", at=t, age_band=age, region=region, acquisition=acq,
                             invited_by=inviter and inviter[0])
            pid = src.create("user", at=t, uid=uid, region=region, acquisition=acq,
                             inviter=inviter and inviter[0], inviter_pid=inviter and inviter[1])
            users.append((uid, pid))
