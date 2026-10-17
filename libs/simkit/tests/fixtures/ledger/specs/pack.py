"""Postings (D45) and accumulators (D46): each account opens with an amount and books two
postings per opening; tasks 7 and 9 extend it."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import amount, cat, ref

from . import kernels as k

PACK = "ledger"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    accts: int = 6


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"bal": amount(asset="USD")})
    p.owner("acct", table=acct, max_live=cfg.accts)
    p.population(acct, n=cfg.accts, initial=0.5,
                 arrivals=dist.poisson_daily(weekly=(1, 1, 1, 1, 1, 1, 1)))
    p.event("opened", owner="acct", cols={"acct_id": ref("acct"), "amount": amount(asset="USD")})
    p.postings("entry", owner="acct", doc="Double-entry postings of an opening", cols={
        "acct_id": ref("acct"), "account": cat("cash", "revenue"),
        "side": cat("debit", "credit"), "amount": amount(asset="USD")})
    p.process("acct_main", owner="acct", kernel=k.acct_main, config=cfg,
              start=p.on_created("acct"), commands=(0,))
