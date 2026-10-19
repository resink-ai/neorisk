"""A cohort that signs up and does nothing else: it shares no decision state with the base."""

from neorisk_simkit.spec import Overlay, dist, std


def apply(o: Overlay, size: int = 2) -> None:
    c = o.cohort("loners", table="user", size=size, execution_owner="loner_id",
                 attrs={"tier": "a"}, refs={"device": std.devices(
                     per_user=dist.categorical({1: 1.0}), table="device", share=0.0)})
    m = o.machine("loner", members=c, initial="new", fields={"device": "ref"},
                  init={"device": std.pick_ref("device")})
    m.state("new", branch={"gone": (1.0, dist.constant(s=60), o.base.signup)})
    m.final("gone")
