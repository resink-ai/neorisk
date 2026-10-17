"""Seeded faults (spec §11 mutation tests): fault 0 is correct; each other fault breaks one
law, and the run must fail on exactly that law."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, law, std
from neorisk_simkit.spec.types import amount, cat, i32, opt, ref

from . import kernels as k

PACK = "mutants"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    accts: int = 4
    cap: int = 300
    fault: int = 0


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True,
                   cols={"hold": opt(ref("hold")), "claims": i32()})
    p.ids("claim", "hold")
    p.owner("acct", table=acct, max_live=cfg.accts)
    p.population(acct, n=cfg.accts, initial=1.0)
    pool = p.shard("pool", key="pool", n=1, items=None,
                   state={"remaining": "i64", "granted": "i64"},
                   init=std.capped_pool.init(cfg.cap))
    usd = amount(asset="USD")
    claim = p.request("claim", frm="acct", to=pool, payload={"amount": usd},
                      response_payload={"amount": usd}, responses=("granted", "rejected"),
                      latency=dist.constant(ms=100))
    a = {"acct_id": ref("acct")}
    p.event("funded", owner="acct", cols={**a, "amount": usd})
    p.event("credited", owner="acct", cols={**a, "claim_id": ref("claim"), "amount": usd})
    p.event("held", owner="acct", cols={**a, "hold_id": ref("hold")})
    p.event("freed", owner="acct", cols={**a, "hold_id": ref("hold")})
    p.event("granted", shard="pool", cols={"claim_id": ref("claim"), "amount": usd,
                                           "remaining_after": usd})
    p.event("denied", shard="pool", cols={"claim_id": ref("claim"), "amount": usd})
    p.postings("entry", owner="acct", cols={**a, "account": cat("cash", "bonus"),
                                            "side": cat("debit", "credit"), "amount": usd})
    p.process("acct_main", owner="acct", kernel=k.acct_main, config=cfg,
              start=p.on_created("acct"), requests={"claim": claim},
              on_response={("claim", "granted"): k.R_GRANTED,
                           ("claim", "rejected"): k.R_REJECTED},
              commands=k.ACCT_COMMANDS)
    p.process("pool_desk", shard=pool, kernel=k.pool_desk, config=cfg,
              on_request={"claim": k.C_CLAIM})
    # declaration order is evaluation order (Task 10): each fault trips its own law first
    p.check("chk.one_grant", law.at_most_once("granted", key="claim_id"), required=True)
    p.check("chk.pool_cap", law.total_le("granted.amount", cfg.cap), required=True)
    p.check("chk.pool_remaining", law.never_negative("pool.remaining"), required=True)
    p.check("chk.credit_le_funded", law.sum_le("credited.amount", "funded.amount",
                                               by="acct_id"), required=True)
    p.check("chk.entries_balance", law.balanced("entry"), required=True)
    p.check("chk.holds_freed", law.resolved("held", by=("freed",), key="hold_id", within="1h"),
            required=True)
    p.check("chk.funded_positive", law.never_negative("funded.amount"))
