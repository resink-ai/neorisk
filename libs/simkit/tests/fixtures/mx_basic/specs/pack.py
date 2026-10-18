"""Machine basics: a branch with an explicit otherwise racing a timer (earliest wins), a
then-chain whose second part falls back on reject, and @action calls."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import cat, i32, ref

from . import kernels as k

PACK = "mx_basic"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    parcels: int = 6
    sent_p: float = 0.5
    max_weight: int = 5


def define(p: Pack, cfg: Config) -> None:
    parcel = p.table("parcel", key="parcel_id", mutable=True, cols={"weight": i32()})
    p.owner("parcel", table=parcel, max_live=cfg.parcels)
    p.population(parcel, n=cfg.parcels, initial=1.0, attrs={"weight": dist.uniform_int(1, 9)})
    pid = {"parcel_id": ref("parcel")}
    p.event("sent", owner="parcel", cols={**pid, "carrier": cat("ups", "dhl")})
    for name in ("lost", "expired", "audited", "audit_failed"):
        p.event(name, owner="parcel", cols=pid)
    p.event("delivered", owner="parcel", cols={**pid, "weight": i32()})
    m = p.machine("ship", owner="parcel", start=p.on_created("parcel"), initial="placed",
                  config=cfg)
    m.state("placed", branch={
        "sent": (cfg.sent_p, dist.constant(s=3600),
                 std.emit("sent", parcel_id=std.actor(),
                          carrier=dist.categorical({"ups": 0.5, "dhl": 0.5}))),
        "lost": (None, dist.constant(s=7200), std.emit("lost", parcel_id=std.actor())),
    }, timer={"expiring": "90m"})
    m.state("expiring", branch={
        "expired": (1.0, None, std.emit("expired", parcel_id=std.actor()))})
    m.state("sent", branch={"done": (1.0, dist.constant(s=600), k.deliver.then(
        k.audit.otherwise(std.emit("audit_failed", parcel_id=std.actor()))))})
    m.final("done", "lost", "expired")
