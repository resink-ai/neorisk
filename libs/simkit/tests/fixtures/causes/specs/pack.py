"""cause_id (D80): request -> shard record -> response, and a timer chain through a commit
that emits only a hidden label row (never a cause, F-17), across step boundaries."""

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import i32, ref

from . import kernels as k

PACK = "causes"
SCHEMA_VERSION = 1


def define(p: Pack, cfg) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"n": i32()})
    p.owner("acct", table=acct, max_live=2)
    p.population(acct, n=2, initial=1.0)
    desk = p.shard("desk", key="desk", n=1, items=None, state={})
    ask = p.request("ask", frm="acct", to=desk, payload={"who": ref("acct")},
                    responses=("ok",), latency=dist.constant(ms=200))
    a = {"acct_id": ref("acct")}
    for name in ("opened", "ticked", "answered"):
        p.event(name, owner="acct", cols=a)
    p.event("asked", shard="desk", cols={"who": ref("acct")})
    p.labels("marks", owner="acct", cols={"acct_id": ref("acct")})
    p.process("acct_main", owner="acct", kernel=k.acct_main, start=p.on_created("acct"),
              requests={"ask": ask}, on_response={("ask", "ok"): k.R_OK},
              commands=k.ACCT_COMMANDS)
    p.process("desk_main", shard=desk, kernel=k.desk_main, on_request={"ask": k.C_ASK})
