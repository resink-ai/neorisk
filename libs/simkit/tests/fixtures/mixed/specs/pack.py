"""One owner type with both population and created owners (a `child_of` table), D61.

Two population pays (ordinals 0 and 1) ask the desk at 01:00 with lamport 4 and with the same
`src_seq` (4). Pay 0 first pings the desk at 00:59:59.9 and asks from its response handler, so
with 6h or 1d steps its ask reaches the desk a round after pay 1's; with 1h steps both are
routed together. An `acct` creates a third pay at 01:30, so the type is a created-owner type
too. Sender keys are decided per slot: the population pays key by partition_id, so pay 0's ask
runs first under every step length and thread count."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import i32

from . import kernels as k

PACK = "mixed"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    n: int = 2


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"k": i32()})
    pay = p.table("pay", key="pay_id", mutable=True, child_of="acct",
                  cols={"made": i32()})
    p.owner("acct", table=acct, max_live=1)
    p.owner("pay", table=pay, max_live=cfg.n + 1)
    p.population(acct, n=1, initial=1.0)
    p.population(pay, n=cfg.n, initial=1.0)
    desk = p.shard("desk", key="desk", n=1, items=None, state={})
    ping = p.request("ping", frm="pay", to=desk, payload={"v": i32()},
                     responses=("pong",), latency=dist.constant(ms=100))
    ask = p.request("ask", frm="pay", to=desk, payload={"v": i32()},
                    responses=("ok",), latency=dist.constant(ms=100))
    p.event("asked", shard="desk", cols={"v": i32()})
    p.process("acct_main", owner="acct", kernel=k.acct_main, start=p.on_created("acct"),
              commands=k.ACCT_COMMANDS)
    p.process("pay_main", owner="pay", kernel=k.pay_main, start=p.on_created("pay"),
              requests={"ping": ping, "ask": ask},
              on_response={("ping", "pong"): k.R_PONG, ("ask", "ok"): k.R_OK},
              commands=k.PAY_COMMANDS)
    p.process("desk_ping", shard=desk, kernel=k.desk_ping, on_request={"ping": k.C_PINGED})
    p.process("desk_ask", shard=desk, kernel=k.desk_ask, on_request={"ask": k.C_ASKED})
