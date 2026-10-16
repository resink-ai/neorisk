"""Bounty hunters: small rings that farm the referral program, then go dormant.

A ring is one hunter plus the zombie accounts they invite. Hunter and zombies run under one
campaign owner (execution_owner="campaign_id"), so the hunter can wait on its zombies without
cross-owner messages. Campaigns run in parallel; their bonus claims go to the same capped
referral_pool shard as everyone else's, so a ring arriving late in the month can drain the
budget and cause ordinary claims to be rejected (reported as interference).

    datagen run examples/ecommerce --profile full --overlay bounty_hunters \
        --set bounty_hunters.size=500 --set bounty_hunters.share_device=0.8
"""

from neorisk_simkit.spec import Overlay, dist, std


def apply(o: Overlay,
          size: int = 300,                                      # hunters (rings)
          zombies: dist.Dist = dist.negbinom(mean=12, disp=0.5, min=5, max=30),
          share_device: float = 0.7,                            # zombie reuses a hunter device
          devices_per_ring: dist.Dist = dist.uniform_int(1, 4),
          arrive: dist.Dist = dist.burst(start="day 10", span="30d"),
          qualify_timeout: str = "14d",
          order_above_min: float = 0.05,                        # zombie order ~5% over minimum
          zombie_order_p: float = 0.85) -> None:

    camp = o.cohort("bounty_hunter", table="user", size=size, arrivals=arrive,
                    execution_owner="campaign_id",              # hunter + zombies = one owner
                    suppress=["shopper_journey", "inviter", "invitee"],
                    attrs={"acquisition": dist.categorical({"organic": .4, "social_ad": .6})},
                    refs={"device": std.device_pool(per_owner=devices_per_ring)})

    # ---------------------------------------------------------------- hunter
    h = o.machine("hunter", members=camp, initial="new")
    h.state("new", branch={"inviting": (
        1.0, dist.lognormal(median_s=900),
        o.base.signup.then(std.spawn_members(
            "zombie", n=zombies, via=o.base.invite,
            refs={"device": std.share_with_parent(share_device)},
            stagger=dist.exp(mean_s=240))))})
    h.state("inviting", join={"collecting": ("zombie_paid", "all_spawned")},
            timer={"collecting": qualify_timeout}, late="count")
    h.state("collecting", repeat=(dist.exp(mean_s=60), 1.0, o.base.claim_inviter_bonus),
            until=std.no_unclaimed("zombie_paid"), then="gone")
    h.final("gone", status="dormant")

    # ---------------------------------------------------------------- zombie
    z = o.machine("zombie", members=camp.spawned("zombie"), initial="invited")
    z.state("invited", branch={
        "ordered": (zombie_order_p, dist.lognormal(median_s=600),
                    o.base.signup_via_invite.then(o.base.first_order.with_params(
                        amount=std.near("referral.min_order", above=order_above_min)))),
        "otherwise": (1 - zombie_order_p, None, None),
    })
    z.state("ordered", request={"paid": o.base.claim_invitee_bonus},   # capped pool shard
            on_reject="gone", timeout="1m")
    z.state("paid", branch={"gone": (1.0, dist.exp(mean_s=300), std.send_parent("zombie_paid"))})
    z.final("gone", "otherwise", status="dormant")

    # ---------------------------------------------------------------- labels (hidden)
    o.label(camp, role={"hunter", "zombie"}, outcome=("attempted", "qualified", "paid"),
            available_at=std.after("paid", dist.gamma(mean_days=30)))
