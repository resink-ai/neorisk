"""A gang: one boss and its minions under one gang owner (execution owner, D74). Minions sign
up through the boss and claim from the base pot; the boss joins on their payouts."""

from neorisk_simkit.spec import Overlay, dist, std


def apply(o: Overlay, size: int = 2, minions: int = 2, arrive_day: float = 0.0,
          share_device: float = 0.5, wait: str = "2h") -> None:
    gang = o.cohort("gang", table="user", size=size,
                    arrivals=dist.burst(start_day=arrive_day, span_days=0.01),
                    execution_owner="gang_id", suppress=["user_main"], attrs={"tier": "b"},
                    refs={"device": std.devices(per_user=dist.categorical({2: 1.0}),
                                                table="device", share=0.0)})
    boss = o.machine("boss", members=gang, initial="new", fields={"device": "ref"},
                     init={"device": std.pick_ref("device")})
    boss.state("new", branch={"recruiting": (1.0, dist.constant(s=60), o.base.signup.then(
        std.label("boss", "attempted")).then(std.spawn(
            "minion", n=minions,
            fields={"device": std.pick_ref("device", parent_share=share_device)})))})
    boss.state("recruiting", join={"done": "paid"}, timer={"done": wait}, late="count")
    boss.final("done")
    minion = o.machine("minion", members=gang.spawned("minion"), initial="invited",
                       max_instances=8, fields={"device": "ref", "paid": "i64"},
                       member={"invited_by": std.parent()})
    minion.state("invited", branch={"claiming": (1.0, dist.constant(s=300), o.base.signup_invited
                                                 .then(std.label("minion", "attempted")))})
    minion.state("claiming", request={"paid": o.base.claim}, on_reject="gone", timeout="1m")
    minion.state("paid", branch={"gone": (1.0, None, o.base.pay_bonus.then(
        std.label("minion", "paid")).then(std.send_parent("paid")))})
    minion.final("gone")
    o.label(gang, roles=("boss", "minion"), outcomes=("attempted", "paid"),
            available_after=dist.constant(s=86_400))
