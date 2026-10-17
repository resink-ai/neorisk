"""Owner creation (OB_CREATE), one-way messages (_send_) and shard addressing."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import amount, i32, ref

from . import kernels as k

PACK = "spawn"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    accts: int = 3
    bad_shard: int = 0                 # 1: address the request to a shard index past n
    request_delay: int = 0             # > 0: date the request after ctx.t (an error)
    create_on_answer: int = 0          # 1: create the payment when the answer arrives
    rounds: int = 1                    # request/answer round trips per account


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"n": i32()})
    pay = p.table("pay", key="pay_id", mutable=True,
                  cols={"acct_id": ref("acct"), "amt": amount(asset="USD")})
    p.owner("acct", table=acct, max_live=cfg.accts)
    p.owner("pay", table=pay, max_live=cfg.accts * cfg.rounds)
    p.population(acct, n=cfg.accts, initial=1.0)
    desk = p.shard("desk", key="desk", n=2, items=None, state={})
    tick = p.message("tick", frm="acct", to=desk, payload={"v": i32()},
                     latency=dist.constant(ms=50))
    ask = p.request("ask", frm="acct", to=desk, payload={"v": i32()}, responses=("ok",),
                    latency=dist.constant(ms=200))
    p.event("spawned", owner="acct", cols={"acct_id": ref("acct"), "pay_id": ref("pay")})
    p.event("answered", owner="acct", cols={"acct_id": ref("acct")})
    p.event("paid", owner="pay", cols={"pay_id": ref("pay"), "acct_id": ref("acct"),
                                       "amt": amount(asset="USD")})
    p.event("ticked", shard="desk", cols={"v": i32()})
    p.event("asked", shard="desk", cols={"v": i32()})
    p.process("acct_main", owner="acct", kernel=k.acct_main, config=cfg,
              start=p.on_created("acct"), messages={"tick": tick}, requests={"ask": ask},
              on_response={("ask", "ok"): k.R_OK}, commands=k.ACCT_COMMANDS)
    p.process("pay_main", owner="pay", kernel=k.pay_main, start=p.on_created("pay"),
              commands=k.PAY_COMMANDS)
    p.process("desk_main", shard=desk, kernel=k.desk_main,
              on_message={"tick": k.C_TICK}, on_request={"ask": k.C_ASK})
