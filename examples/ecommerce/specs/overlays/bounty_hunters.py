"""Bounty hunters: rings of zombie accounts that farm referral bonuses.

A hunter signs up on one or two devices and invites zombies. Each zombie signs up on one of
the hunter's devices, then places one order just above the referral minimum. The claim goes
through the same pool, with the same delay, as everyone's (no timing tell). The hunter cashes
each bonus out in an order. Hunters and zombies are labeled; labels become available about a
month after the ring member's signup. A zombie's label outcome is "attempted" when it joins,
"qualified" when it orders, then "paid" or "rejected" when the pool decides.

Two knobs blur the line between the ring and everyone else (both off by default):

- `stealth_p`: a ring member blends in. A stealth zombie signs up on a device of its own,
  buys an ordinary qualifying product at its list price and then browses like a shopper; a
  stealth hunter browses too and cashes out on ordinary products. Still labeled: the misses.
- `promoters_share`: genuine users who invite many friends. Some friends share the promoter's
  device and open with the cheapest qualifying order, just like zombies; then they shop
  normally. Never labeled: the false alarms.
"""

from __future__ import annotations

import numpy as np

from neorisk_simkit.engine import DAY
from neorisk_simkit.spec.overlay import Overlay

CHANNELS = ("organic", "ads", "social")


def apply(o: Overlay, share: float = 0.002, zombies_mean: float = 8.0,
          arrive_share: float = 0.8, label_delay_days: float = 30.0, stealth_p: float = 0.0,
          promoters_share: float = 0.0, friends_mean: float = 8.0,
          friend_shared_device_p: float = 0.5, friend_cheap_p: float = 0.6) -> None:
    o.cohort("bounty_hunter", kind="user", share=share, arrive_share=arrive_share,
             suppress=["shopper"], redirect={"bonus_credited": "cash_out"})
    o.cohort("zombie", kind="user", suppress=["shopper"],
             redirect={"claim_answered": "claim_outcome"})
    hunter = o.process("user", "hunting", cohort="bounty_hunter", start="hunt",
                       doc="Sign up, spawn zombies, cash bonuses out")
    zombie = o.process("user", "zombie_life", cohort="zombie", start="wait_to_join")

    def cheapest_qualifying_sku(ctx) -> int:
        price = ctx.shared.catalog.price
        ok = [i for i in range(len(price)) if price[i] >= ctx.cfg.min_order_cents]
        return 1 + min(ok, key=lambda i: price[i])

    def popular_qualifying_sku(ctx) -> int:
        """A qualifying SKU drawn by popularity, as an ordinary shopper would pick one."""
        cat = ctx.shared.catalog
        for _ in range(50):
            sku = int(np.searchsorted(cat.cdf, ctx.rng.random(), side="right")) + 1
            if cat.price[sku - 1] >= ctx.cfg.min_order_cents:
                return sku
        return cheapest_qualifying_sku(ctx)

    def stealthy(ctx) -> bool:
        return stealth_p > 0 and ctx.rng.random() < stealth_p

    def variant(ctx) -> str | None:
        return "stealth" if ctx.local.get("stealth") else None

    @hunter.action
    def hunt(ctx, s, cmd):
        rng = ctx.rng
        s.acquisition = CHANNELS[rng.integers(len(CHANNELS))]
        ctx.call("signup", n_devices=1 + int(rng.integers(2)))
        ctx.local["sku"] = cheapest_qualifying_sku(ctx)
        if stealthy(ctx):
            ctx.local["stealth"] = True
            ctx.after(ctx.rng.uniform(0.1, 1.0) * DAY, "session")
        ctx.label(s.uid, "hunter", table="users", campaign_id=s.uid,
                  available_at=ctx.now + label_delay_days * DAY, variant=variant(ctx))
        for _ in range(1 + int(rng.poisson(zombies_mean - 1))):
            ctx.create("user", cohort="zombie", inviter=s.uid, inviter_pid=ctx.self_id,
                       acquisition="invite", devices=list(s.devices))

    @hunter.action
    def cash_out(ctx, s, cmd):
        ctx.after(ctx.rng.uniform(0.2, 2.0) * DAY, "cash_out_order", amount=cmd.amount)

    @hunter.action
    def cash_out_order(ctx, s, cmd):
        if ctx.local.get("stealth"):
            return ctx.call("checkout", device=s.devices[0],
                            lines=[(popular_qualifying_sku(ctx), 1)])
        ctx.call("checkout", device=s.devices[0], lines=[(ctx.local["sku"], 1)],
                 amount=cmd.amount + int(ctx.rng.integers(0, 500)))

    @zombie.action
    def wait_to_join(ctx, s, cmd):
        if stealthy(ctx):
            ctx.local["stealth"] = True
        ctx.after(ctx.rng.uniform(0, 2) * DAY, "join")

    @zombie.action
    def join(ctx, s, cmd):
        rng = ctx.rng
        if ctx.local.get("stealth"):
            ctx.call("signup", n_devices=1)
        else:
            ctx.call("signup", devices=[s.devices[rng.integers(len(s.devices))]])
        ctx.local["label_at"] = ctx.now + label_delay_days * DAY
        ctx.label(s.uid, "zombie", table="users", outcome="attempted", campaign_id=s.inviter,
                  available_at=ctx.local["label_at"], variant=variant(ctx))
        ctx.after(rng.uniform(0.1, 1.0) * DAY, "first_order")

    @zombie.action
    def first_order(ctx, s, cmd):
        stealth = ctx.local.get("stealth", False)
        device = s.devices[0]
        sku = popular_qualifying_sku(ctx) if stealth else cheapest_qualifying_sku(ctx)
        ctx.label(s.uid, "zombie", table="users", outcome="qualified", campaign_id=s.inviter,
                  available_at=ctx.local["label_at"], variant=variant(ctx))     # its order is sized to qualify
        sid = ctx.new_id("session")
        ctx.emit("session_started", user_id=s.uid, device_id=device, session_id=sid)
        ctx.emit("product_viewed", user_id=s.uid, device_id=device, session_id=sid, sku_id=sku)
        if stealth:                                        # list price, then browse on
            ctx.call("checkout", device=device, lines=[(sku, 1)])
            ctx.after(ctx.rng.uniform(1, 5) * DAY, "session")
            return
        ctx.call("checkout", device=device, lines=[(sku, 1)],
                 amount=ctx.cfg.min_order_cents + int(ctx.rng.integers(0, 150)))

    @zombie.action
    def claim_outcome(ctx, s, cmd):
        ctx.label(s.uid, "zombie", table="users", outcome="paid" if cmd.ok else "rejected",
                  campaign_id=s.inviter, available_at=ctx.local["label_at"], variant=variant(ctx))

    if promoters_share <= 0:
        return
    # genuine promoters: base shoppers who also bring friends in; nobody here is labeled
    o.cohort("promoter", kind="user", share=promoters_share, arrive_share=arrive_share)
    o.cohort("promoted_friend", kind="user", suppress=["shopper"])
    promoting = o.process("user", "promoting", cohort="promoter", start="plan_invites")
    befriended = o.process("user", "befriended", cohort="promoted_friend", start="friend_waits")

    @promoting.action
    def plan_invites(ctx, s, cmd):                     # after the base signup has run
        ctx.after(ctx.rng.uniform(0.5, 3.0) * DAY, "invite_friends")

    @promoting.action
    def invite_friends(ctx, s, cmd):
        rng = ctx.rng
        for _ in range(1 + int(rng.poisson(friends_mean - 1))):
            shared = rng.random() < friend_shared_device_p
            ctx.create("user", cohort="promoted_friend", inviter=s.uid, inviter_pid=ctx.self_id,
                       acquisition="invite", devices=[s.devices[0]] if shared else [])

    @befriended.action
    def friend_waits(ctx, s, cmd):
        ctx.after(ctx.rng.uniform(0, 7) * DAY, "join_friend")

    @befriended.action
    def join_friend(ctx, s, cmd):
        if s.devices:
            ctx.call("signup", devices=list(s.devices))
        else:
            ctx.call("signup")
        ctx.after(ctx.rng.uniform(0.1, 2.0) * DAY, "first_friend_order")

    @befriended.action
    def first_friend_order(ctx, s, cmd):
        rng, device = ctx.rng, s.devices[0]
        cheap = rng.random() < friend_cheap_p
        sku = cheapest_qualifying_sku(ctx) if cheap else popular_qualifying_sku(ctx)
        sid = ctx.new_id("session")
        ctx.emit("session_started", user_id=s.uid, device_id=device, session_id=sid)
        ctx.emit("product_viewed", user_id=s.uid, device_id=device, session_id=sid, sku_id=sku)
        if cheap:                                      # a deal-seeker sizes it to qualify
            ctx.call("checkout", device=device, lines=[(sku, 1)],
                     amount=ctx.cfg.min_order_cents + int(rng.integers(0, 150)))
        else:
            ctx.call("checkout", device=device, lines=[(sku, 1)])
        ctx.after(rng.uniform(1, 5) * DAY, "session")
