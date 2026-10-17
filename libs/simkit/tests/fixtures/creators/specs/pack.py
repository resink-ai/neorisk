"""Owners that create owners in several commits, across step boundaries (spec §12 invariance).

Each `acct` creates one `pay` at start, two in one commit at a staggered time (higher accounts
earlier) and one more 3 h later. Every `pay` draws randomness at creation and again from a
timer at the next 8 h boundary, where payments of different accounts tie at an equal
`(event_time, lamport)`. Each payment of a pair creates a `refund` owner at its start, in the
same step as the payment itself (a creator that is provisional when it creates), which draws
and ticks the same way.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack
from neorisk_simkit.spec.types import amount, i32, ref

from . import kernels as k

PACK = "creators"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    accts: int = 6


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"n": i32()})
    pay = p.table("pay", key="pay_id", mutable=True,
                  cols={"acct_id": ref("acct"), "amt": amount(asset="USD")})
    p.owner("acct", table=acct, max_live=cfg.accts)
    refund = p.table("refund", key="refund_id", mutable=True, cols={"pay_id": ref("pay")})
    p.owner("pay", table=pay, max_live=4 * cfg.accts)
    p.owner("refund", table=refund, max_live=2 * cfg.accts)
    p.population(acct, n=cfg.accts, initial=1.0)
    p.event("spawned", owner="acct", cols={"acct_id": ref("acct"), "pay_id": ref("pay")})
    p.event("paid", owner="pay", cols={"pay_id": ref("pay"), "acct_id": ref("acct"),
                                       "draw": i32()})
    p.event("ticked", owner="pay", cols={"pay_id": ref("pay"), "acct_id": ref("acct"),
                                         "draw": i32()})
    p.event("refunded", owner="refund", cols={"refund_id": ref("refund"), "pay_id": ref("pay"),
                                              "phase": i32(), "draw": i32()})
    p.process("acct_main", owner="acct", kernel=k.acct_main, config=cfg,
              start=p.on_created("acct"), commands=k.ACCT_COMMANDS)
    p.process("pay_main", owner="pay", kernel=k.pay_main, start=p.on_created("pay"),
              commands=k.PAY_COMMANDS)
    p.process("refund_main", owner="refund", kernel=k.refund_main,
              start=p.on_created("refund"), commands=k.PAY_COMMANDS)
