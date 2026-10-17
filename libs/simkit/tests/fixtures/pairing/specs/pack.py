"""Request/response pairing (D40): the desk answers each request exactly once in mode 0;
mode 1 rejects a request, mode 2 answers twice, mode 3 answers a message."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import i32, ref

from . import kernels as k

PACK = "pairing"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    accts: int = 2
    mode: int = 0


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"n": i32()})
    p.owner("acct", table=acct, max_live=cfg.accts)
    p.population(acct, n=cfg.accts, initial=1.0)
    desk = p.shard("desk", key="desk", n=1, items=None, state={})
    ask = p.request("ask", frm="acct", to=desk, payload={"v": i32()}, responses=("ok",),
                    latency=dist.constant(ms=100))
    tick = p.message("tick", frm="acct", to=desk, payload={"v": i32()},
                     latency=dist.constant(ms=50))
    p.event("answered", owner="acct", cols={"acct_id": ref("acct")})
    p.event("asked", shard="desk", cols={"v": i32()})
    p.process("acct_main", owner="acct", kernel=k.acct_main, start=p.on_created("acct"),
              requests={"ask": ask}, messages={"tick": tick},
              on_response={("ask", "ok"): k.R_OK}, commands=k.ACCT_COMMANDS)
    p.process("desk_main", shard=desk, kernel=k.desk_main, config=cfg,
              on_request={"ask": k.C_ASK}, on_message={"tick": k.C_TICK})
