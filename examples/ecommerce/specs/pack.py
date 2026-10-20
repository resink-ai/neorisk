"""E-commerce shoppers with a referral program.

Shoppers sign up, run sessions (view products, sometimes check out), place orders, sometimes
return them, and sometimes move region. A referred shopper's first qualifying order claims its
inviter's bonus, after a delay, from a monthly budget held by the `referral_pool` shard. The
pool pays (or rejects) and credits the inviter by message.

Extension points for overlays: `signup` (payload `devices` or `n_devices`), `place_order`
(payload `device`, `sku`, `amount`, `quantity`) and `bonus_credited` (no-op for shoppers).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from neorisk_simkit.engine import DAY
from neorisk_simkit.spec import Latency, Pack, amount, cat, i32, i64, opt, ref
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


@dataclass
class User:
    uid: int = 0
    region: str = ""
    acquisition: str = ""
    inviter: int | None = None        # the inviter's user id ...
    inviter_pid: int | None = None    # ... and partition
    devices: list[int] = field(default_factory=list)
    claimed: bool = False             # the referral claim has been made


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
        "user_id": ref("users"), "sku_id": ref("skus"), "quantity": i32(min=1),
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
    account = user.process("account", doc="Signup, orders and referral claims")
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
    def place_order(ctx, s, cmd):
        cfg, rng = ctx.cfg, ctx.rng
        qty = cmd.payload.get("quantity", 1)
        oid = ctx.insert("orders", user_id=s.uid, sku_id=cmd.sku, quantity=qty,
                         amount=cmd.amount)
        ctx.emit("order_placed", user_id=s.uid, device_id=cmd.device, order_id=oid,
                 sku_id=cmd.sku, quantity=qty, amount=cmd.amount)
        if rng.random() < cfg.return_p:
            ctx.after(rng.uniform(1, 20) * DAY, "return_order", order=oid, amount=cmd.amount)
        if s.inviter and not s.claimed and cmd.amount >= cfg.min_order_cents:
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
            sku = int(viewed[-1])
            qty = 1 + int(rng.poisson(0.3))
            ctx.call("place_order", device=device, sku=sku, quantity=qty,
                     amount=qty * int(cat_.price[sku - 1]))
        if rng.random() < cfg.move_p_per_day / max(cfg.sessions_per_day, 1e-9):
            s.region = REGIONS[rng.integers(len(REGIONS))]
            ctx.emit("address_changed", user_id=s.uid, region=s.region)
        ctx.after(rng.exponential(DAY / cfg.sessions_per_day), "session")

    @p.source
    def population(src):
        cfg, rng = src.cfg, src.rng
        price = np.exp(rng.normal(np.log(2500), 0.8, cfg.skus)).astype(np.int64) + 99
        category = rng.integers(0, len(CATEGORIES), cfg.skus)
        for i in range(cfg.skus):
            src.insert("skus", category=CATEGORIES[category[i]], price=int(price[i]))
        w = 1.0 / np.arange(1, cfg.skus + 1) ** cfg.sku_zipf
        src.share("catalog", price=price, cdf=np.cumsum(w) / w.sum())
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
