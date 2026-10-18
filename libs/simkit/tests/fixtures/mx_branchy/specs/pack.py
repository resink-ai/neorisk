"""Machine branches by owner category (std.p_by), a fallback that is itself rejected, and a
declared on_reject target."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import cat, i32, ref

from . import kernels as k

PACK = "mx_branchy"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    accts: int = 8
    max_weight: int = 5


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True,
                   cols={"tier": cat("gold", "basic"), "weight": i32()})
    p.owner("acct", table=acct, max_live=cfg.accts)
    p.population(acct, n=cfg.accts, initial=1.0,
                 attrs={"tier": dist.categorical({"gold": 0.5, "basic": 0.5}),
                        "weight": dist.uniform_int(1, 9)})
    aid = {"acct_id": ref("acct")}
    for name in ("picked_gold", "picked_other", "checked"):
        p.event(name, owner="acct", cols=aid)
    m = p.machine("flow", owner="acct", start=p.on_created("acct"), initial="pick",
                  config=cfg)
    m.state("pick", branch={
        "gold": (std.p_by("tier", {"gold": 1.0}, otherwise=0.0), None,
                 std.emit("picked_gold", acct_id=std.actor())),
        "other": (None, None, std.emit("picked_other", acct_id=std.actor())),
    })
    m.state("gold", branch={"done": (1.0, dist.constant(s=60),
                                     k.check.otherwise(k.refuse))}, on_reject="failed")
    m.final("done", "other", "failed")
