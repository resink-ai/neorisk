"""Kernels that break the action interface on purpose; checked mode must catch each."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack
from neorisk_simkit.spec.types import i32, ref

from . import kernels as k

PACK = "bad_abi"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    mode: int = 0          # 0 write-then-reject, 1 emit without reserve, 2 past timer, 3 write-then-retry


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"n": i32()})
    p.owner("acct", table=acct, max_live=3)
    p.population(acct, n=3, initial=1.0)
    p.event("e", owner="acct", cols={"acct_id": ref("acct")})
    p.process("bad", owner="acct", kernel=k.bad, config=cfg, start=p.on_created("acct"),
              commands=(0,))
