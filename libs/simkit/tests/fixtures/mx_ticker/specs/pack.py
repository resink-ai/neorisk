"""A repeat state with no then= (§04): it repeats until its timer leaves; the repeat count
saturates at its cap instead of ending the instance (Task 7 ruling)."""

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import i32, ref

PACK = "mx_ticker"
SCHEMA_VERSION = 1


def define(p: Pack, cfg) -> None:
    clock = p.table("clock", key="clock_id", mutable=True, cols={})
    p.owner("clock", table=clock, max_live=2)
    p.population(clock, n=2, initial=1.0)
    p.event("tick", owner="clock", cols={"clock_id": ref("clock"), "rep": i32()})
    p.machine("ticker", owner="clock", start=p.on_created("clock"), initial="run").state(
        "run", repeat=(dist.constant(s=60), 1.0,
                       std.emit("tick", clock_id=std.actor(), rep=std.field("rep"))),
        timer={"stop": dist.constant(s=570)}).final("stop")
