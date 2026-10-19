"""One campaign: a hunter spawns three zombies 3h43m apart from day 12 09:14:00; each orders,
claims and reports back; the third finds the cap exhausted."""

from neorisk_simkit.spec import Overlay, dist, std

HUNT_AT_S = 12 * 86_400 + 9 * 3_600 + 14 * 60
STAGGER_S = 3 * 3_600 + 43 * 60


def apply(o: Overlay, zombies: int = 3) -> None:
    camp = o.cohort("campaign", table="user", size=1, execution_owner="campaign_id")
    h = o.machine("hunter", members=camp, initial="new")
    h.state("new", branch={"recruiting": (1.0, dist.constant(s=HUNT_AT_S), std.label(
        "hunter", "attempted").then(std.spawn("zombie", n=zombies,
                                               stagger=dist.constant(s=STAGGER_S))))})
    h.state("recruiting", join={"collecting": "zombie_paid"}, timer={"collecting": "1d"},
            late="count")
    h.state("collecting", branch={"gone": (1.0, None, std.label("hunter", "paid"))})
    h.final("gone")
    z = o.machine("zombie", members=camp.spawned("zombie"), initial="invited",
                  max_instances=4, fields={"paid": "i64"}, member={"invited_by": std.parent()})
    z.state("invited", branch={"claiming": (1.0, None, o.base.first_order.then(
        std.label("zombie", "qualified")))})
    z.state("claiming", request={"paid": o.base.claim}, on_reject="leaving", timeout="1m")
    z.state("paid", branch={"gone": (1.0, None, o.base.pay_bonus.then(
        std.label("zombie", "paid")).then(std.send_parent("zombie_paid")))})
    z.state("leaving", branch={"gone": (1.0, None, std.label("zombie", "attempted"))})
    z.final("gone")
    o.label(camp, roles=("hunter", "zombie"), outcomes=("attempted", "qualified", "paid"),
            available_after=dist.constant(s=30 * 86_400))
