"""Bounty hunters: rings of zombie accounts that farm referral bonuses.

A hunter signs up on one or two devices and invites zombies. Each zombie signs up on one of
the hunter's devices, then places one order just above the referral minimum. The claim goes
through the same pool, with the same delay, as everyone's (no timing tell). The hunter cashes
each bonus out in an order. Hunters and zombies are labeled; labels become available about a
month after the ring member's signup. A zombie's label outcome is "attempted" when it joins,
"qualified" when it orders, then "paid" or "rejected" when the pool decides.
"""

from __future__ import annotations

from neorisk_simkit.engine import DAY
from neorisk_simkit.spec.overlay import Overlay

CHANNELS = ("organic", "ads", "social")


def apply(o: Overlay, share: float = 0.002, zombies_mean: float = 8.0,
          arrive_share: float = 0.8, label_delay_days: float = 30.0) -> None:
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

    @hunter.action
    def hunt(ctx, s, cmd):
        rng = ctx.rng
        s.acquisition = CHANNELS[rng.integers(len(CHANNELS))]
        ctx.call("signup", n_devices=1 + int(rng.integers(2)))
        ctx.local["sku"] = cheapest_qualifying_sku(ctx)
        ctx.label(s.uid, "hunter", campaign_id=s.uid,
                  available_at=ctx.now + label_delay_days * DAY)
        for _ in range(1 + int(rng.poisson(zombies_mean - 1))):
            ctx.create("user", cohort="zombie", inviter=s.uid, inviter_pid=ctx.self_id,
                       acquisition="invite", devices=list(s.devices))

    @hunter.action
    def cash_out(ctx, s, cmd):
        ctx.after(ctx.rng.uniform(0.2, 2.0) * DAY, "cash_out_order", amount=cmd.amount)

    @hunter.action
    def cash_out_order(ctx, s, cmd):
        ctx.call("checkout", device=s.devices[0], lines=[(ctx.local["sku"], 1)],
                 amount=cmd.amount + int(ctx.rng.integers(0, 500)))

    @zombie.action
    def wait_to_join(ctx, s, cmd):
        ctx.after(ctx.rng.uniform(0, 2) * DAY, "join")

    @zombie.action
    def join(ctx, s, cmd):
        rng = ctx.rng
        device = s.devices[rng.integers(len(s.devices))]
        ctx.call("signup", devices=[device])
        ctx.local["label_at"] = ctx.now + label_delay_days * DAY
        ctx.label(s.uid, "zombie", outcome="attempted", campaign_id=s.inviter,
                  available_at=ctx.local["label_at"])
        ctx.after(rng.uniform(0.1, 1.0) * DAY, "first_order")

    @zombie.action
    def first_order(ctx, s, cmd):
        device, sku = s.devices[0], cheapest_qualifying_sku(ctx)
        ctx.label(s.uid, "zombie", outcome="qualified", campaign_id=s.inviter,
                  available_at=ctx.local["label_at"])     # its order is sized to qualify
        sid = ctx.new_id("session")
        ctx.emit("session_started", user_id=s.uid, device_id=device, session_id=sid)
        ctx.emit("product_viewed", user_id=s.uid, device_id=device, session_id=sid, sku_id=sku)
        ctx.call("checkout", device=device, lines=[(sku, 1)],
                 amount=ctx.cfg.min_order_cents + int(ctx.rng.integers(0, 150)))

    @zombie.action
    def claim_outcome(ctx, s, cmd):
        ctx.label(s.uid, "zombie", outcome="paid" if cmd.ok else "rejected",
                  campaign_id=s.inviter, available_at=ctx.local["label_at"])
