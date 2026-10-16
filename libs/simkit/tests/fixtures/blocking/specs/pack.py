"""Blocking suspension: commands queued before a response run at the response time."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import i32, ref

from . import kernels as k

PACK = "blocking"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    accts: int = 2


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"n": i32()})
    p.owner("acct", table=acct, max_live=cfg.accts)
    p.population(acct, n=cfg.accts, initial=1.0)
    ledger = p.shard("ledger", key="ledger", n=1, items=None, state={})
    note = p.request("note", frm="acct", to=ledger, payload={"v": i32()}, responses=("ack",),
                     latency=dist.constant(ms=100))
    p.event("later", owner="acct", cols={"acct_id": ref("acct")})
    p.event("acked", owner="acct", cols={"acct_id": ref("acct")})
    p.event("noted", shard="ledger", cols={"v": i32()})
    p.process("acct_main", owner="acct", kernel=k.acct_main, start=p.on_created("acct"),
              requests={"note": note}, on_response={("note", "ack"): k.R_ACK},
              commands=k.ACCT_COMMANDS)
    p.process("ledger_desk", shard=ledger, kernel=k.ledger_desk, on_request={"note": k.C_NOTE})
