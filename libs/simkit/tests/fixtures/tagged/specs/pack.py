"""Hidden label records (D76): written to labels/, never to events/ or replay."""

from neorisk_simkit.spec import Pack
from neorisk_simkit.spec.types import boolean, cat, i32, ref, ts

from . import kernels as k

PACK = "tagged"
SCHEMA_VERSION = 1


def define(p: Pack, cfg) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"n": i32()})
    p.owner("acct", table=acct, max_live=3)
    p.population(acct, n=3, initial=1.0)
    p.event("seen", owner="acct", cols={"acct_id": ref("acct")})
    p.labels("tags", owner="acct", cols={
        "target_id": ref("acct"), "role": cat("bad", "good"), "outcome": cat("tried", "done"),
        "final_label": boolean(), "label_available_at": ts()})
    p.process("acct_main", owner="acct", kernel=k.acct_main, start=p.on_created("acct"))
