"""Bounty hunters (brief: Abuse): rings that farm the referral program, then go dormant.

A ring is one hunter plus the zombie accounts it invites, all executed by one campaign owner
(execution owner, D74): the hunter waits on its zombies with a join, without cross-owner
messages, and campaigns run in parallel. Zombies claim from the same capped referral_pool shard
as every shopper, so rings that arrive when the budget is low drain it and ordinary claims are
rejected (interference, D79). Members are user rows (entities/user, origin "member"); they emit
only base events through the actions the base pack exposes; hidden labels go to labels/.

    datagen run examples/ecommerce --profile full --overlay bounty_hunters \
        --set bounty_hunters.size=500 --set bounty_hunters.share_device=0.8

`claim_timeout` is the zombie's claim request timeout (D67). Keep it well above the claim
latency (300 ms minimum); below it every grant arrives late and is refunded to the pool
(`bonus_refunded`, `machines.zombie.late_grants`), which the tests use to exercise F-35.
"""

from neorisk_simkit.spec import Overlay, dist, std

AGE = {"18-24": 0.5, "25-34": 0.5}


def apply(o: Overlay, size: int = 300, zombies_mean: float = 12.0, share_device: float = 0.7,
          arrive_day: float = 10.0, arrive_span_days: float = 30.0, qualify_timeout: str = "14d",
          order_above_min: float = 0.05, zombie_order_p: float = 0.85,
          claim_timeout: str = "1m") -> None:
    min_order = o.param("referral.min_order")
    camp = o.cohort("campaign", table="user", size=size,
                    arrivals=dist.burst(start_day=arrive_day, span_days=arrive_span_days),
                    execution_owner="campaign_id", suppress=["shopper"],
                    attrs={"age_band": dist.categorical(AGE),
                           "region": dist.uniform_int(0, 49)},
                    refs={"device": std.devices(
                        per_user=dist.categorical({1: .25, 2: .25, 3: .25, 4: .25}),
                        table="device", share=0.0)})

    # ---------------------------------------------------------------- hunter
    h = o.machine("hunter", members=camp, initial="new", reads={"sku": "sku"},
                  fields={"device": "ref", "amount": "i64", "paid": "i64"},
                  init={"device": std.pick_ref("device"),
                        "amount": std.near(3 * min_order, above=1.0)},
                  member={"acquisition": "social_ad"})
    # spawn on the transition into the join state (a state may not both spawn and join)
    h.state("new", branch={"inviting": (
        1.0, dist.lognormal(median_s=900),
        o.base.signup.then(std.label("hunter", "attempted")).then(std.spawn(
            "zombie", n=dist.geometric(mean=zombies_mean, max=30),
            stagger=dist.exp(mean_s=240),
            fields={"device": std.pick_ref("device", parent_share=share_device),
                    "amount": std.near(min_order, above=order_above_min)})))})
    # the hunter joins once, so `jn` (a lifetime counter) is exactly its zombies paid in time
    h.state("inviting", join={"collecting": "zombie_paid"}, timer={"collecting": qualify_timeout},
            late="count")
    h.state("collecting", repeat=(dist.exp(mean_s=3600), 1.0, o.base.quick_order),
            max_repeats=std.field("jn"), then="done")     # one cash-out order per paid zombie
    h.state("done", branch={"gone": (1.0, None, std.label("hunter", "qualified"))})
    h.final("gone")

    # ---------------------------------------------------------------- zombie
    z = o.machine("zombie", members=camp.spawned("zombie"), initial="invited",
                  max_instances=32, reads={"sku": "sku"},
                  fields={"device": "ref", "amount": "i64", "paid": "i64", "claim": "ref"},
                  member={"acquisition": "invite", "referred": 1, "invited_by": std.parent()})
    z.state("invited", branch={
        "ordered": (zombie_order_p, dist.lognormal(median_s=600),
                    o.base.signup_invited.then(std.label("zombie", "attempted"))
                    .then(o.base.quick_order).then(std.label("zombie", "qualified"))),
        "dormant": (None, dist.lognormal(median_s=600),
                    o.base.signup_invited.then(std.label("zombie", "attempted")))})
    z.state("ordered", request={"paid": o.base.claim_bonus}, on_reject="gone",
            timeout=claim_timeout)
    z.state("paid", branch={"gone": (1.0, dist.exp(mean_s=300), o.base.pay_referral.then(
        std.label("zombie", "paid")).then(std.send_parent("zombie_paid")))})
    z.final("gone", "dormant")

    # ---------------------------------------------------------------- labels (hidden)
    o.label(camp, roles=("hunter", "zombie"), outcomes=("attempted", "qualified", "paid"),
            available_after=dist.gamma(mean_days=30))
