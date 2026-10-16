"""Instants: one account that emits `mark` events at fixed offsets from the run start, so the
exact boundary instants (start - 1us, start, step ends, midnight) occur deterministically."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack
from neorisk_simkit.spec.types import i32, ref

from . import kernels as k

PACK = "instants"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    accts: int = 1


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"count": i32()})
    p.owner("acct", table=acct, max_live=cfg.accts)
    p.population(acct, n=cfg.accts, initial=1.0)
    p.event("mark", owner="acct", cols={"acct_id": ref("acct"), "n": i32()})
    p.process("acct_main", owner="acct", kernel=k.acct_main, config=cfg,
              start=p.on_created("acct"), commands=k.ACCT_COMMANDS)
