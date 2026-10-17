"""Created owners send requests that tie with other senders (D61).

`acct` creates a `pay` at 00:50 (commit lamport 2); the pay asks the desk at 01:00 with
lamport 4. A `peer` (declared after `pay`, so a higher partition type) asks at 01:00 with
lamport 4 too, so both requests carry cause 4. With
30m or 1h steps the pay is dense by 01:00; with 6h or 1d steps it is still provisional."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import i32, ref

from . import kernels as k

PACK = "relay"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    n: int = 2


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"k": i32()})
    pay = p.table("pay", key="pay_id", mutable=True, cols={"acct_id": ref("acct")})
    peer = p.table("peer", key="peer_id", mutable=True, cols={"k": i32()})
    p.owner("acct", table=acct, max_live=cfg.n)
    p.owner("pay", table=pay, max_live=cfg.n)
    p.owner("peer", table=peer, max_live=cfg.n)
    p.population(acct, n=cfg.n, initial=1.0)
    p.population(peer, n=cfg.n, initial=1.0)
    desk = p.shard("desk", key="desk", n=1, items=None, state={})
    ask_pay = p.request("ask_pay", frm="pay", to=desk, payload={"v": i32()},
                        responses=("ok",), latency=dist.constant(ms=100))
    ask_peer = p.request("ask_peer", frm="peer", to=desk, payload={"v": i32()},
                         responses=("ok",), latency=dist.constant(ms=100))
    p.event("asked", shard="desk", cols={"v": i32()})
    p.process("acct_main", owner="acct", kernel=k.acct_main, start=p.on_created("acct"),
              commands=k.ACCT_COMMANDS)
    p.process("pay_main", owner="pay", kernel=k.pay_main, start=p.on_created("pay"),
              requests={"ask": ask_pay}, on_response={("ask_pay", "ok"): k.R_OK},
              commands=k.ASKER_COMMANDS)
    p.process("peer_main", owner="peer", kernel=k.peer_main, start=p.on_created("peer"),
              requests={"ask": ask_peer}, on_response={("ask_peer", "ok"): k.R_OK},
              commands=k.PEER_COMMANDS)
    p.process("desk_pay", shard=desk, kernel=k.desk_pay, on_request={"ask_pay": k.C_ASKED})
    p.process("desk_peer", shard=desk, kernel=k.desk_peer, on_request={"ask_peer": k.C_ASKED})
