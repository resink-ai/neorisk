"""Handles that outlive their step inside a shard (spec §12; S2 Task 1).

Each `acct` creates a `ticket` ID and a `pay` owner at start. The ticket reaches the desk shard
in a fast message (same step); the desk keeps it in a `ref` state field and a `Local` ref array
and echoes both two hours later (a later step). The pay owner sends `hello` with a 2 h latency,
so the desk reads `cmd.sender` (payload column 9) of a command queued across seals.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import amount, ref

from . import kernels as k

PACK = "holder"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    accts: int = 3


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"bal": amount(asset="USD")})
    pay = p.table("pay", key="pay_id", mutable=True,
                  cols={"acct_id": ref("acct"), "ticket": ref("ticket")})
    p.ids("ticket")
    p.owner("acct", table=acct, max_live=cfg.accts)
    p.owner("pay", table=pay, max_live=cfg.accts)
    p.population(acct, n=cfg.accts, initial=1.0)
    desk = p.shard("desk", key="desk", n=1, items=None, state={"last": "ref"})
    note = p.message("note", frm="acct", to=desk, payload={"ticket": ref("ticket")},
                     latency=dist.constant(ms=10))
    hello = p.message("hello", frm="pay", to=desk, payload={"ticket": ref("ticket")},
                      latency=dist.constant(s=7200))
    p.event("opened", owner="acct", cols={"acct_id": ref("acct"), "ticket_id": ref("ticket"),
                                          "pay_id": ref("pay")})
    p.event("noted", shard="desk", cols={"ticket_id": ref("ticket")})
    p.event("echoed", shard="desk", cols={"last_id": ref("ticket"), "first_id": ref("ticket")})
    p.event("heard", shard="desk", cols={"ticket_id": ref("ticket"), "sender_id": ref("pay")})
    p.process("acct_main", owner="acct", kernel=k.acct_main, start=p.on_created("acct"),
              messages={"note": note}, commands=(0,))
    p.process("pay_main", owner="pay", kernel=k.pay_main, start=p.on_created("pay"),
              messages={"hello": hello}, commands=(0,))
    p.process("desk_main", shard=desk, kernel=k.desk_main,
              on_message={"note": k.C_NOTE, "hello": k.C_HELLO}, commands=k.DESK_COMMANDS)
