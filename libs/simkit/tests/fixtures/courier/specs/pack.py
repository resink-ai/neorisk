"""Owner-to-owner messages (D73): delivered at t + latency (>= engine.step_max); the target's
presence is judged at the delivery time."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import i64, ref

from . import kernels as k

PACK = "courier"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    accts: int = 5                    # 0..3 exist at the start, 4 arrives during the run
    targets: tuple = (1, 2, 3, 9)     # acct 0 credits each, `send_after_s` after its start:
    #                                   1 live, 2 retires at +1 d (before delivery at +1.5 d),
    #                                   3 retires at +0, 9 does not exist
    send_after_s: int = 43_200
    send4_s: int = -1                 # >= 0: acct 0 also credits acct 4, at this offset
    latency_s: int = 86_400


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"bal": i64()})
    p.owner("acct", table=acct, max_live=cfg.accts)
    p.population(acct, n=cfg.accts, initial=0.8)
    credit = p.message("credit", frm="acct", to="acct", payload={"amount": i64()},
                       latency=dist.constant(s=cfg.latency_s))
    p.event("credited", owner="acct", cols={"acct_id": ref("acct"), "sender": ref("acct"),
                                            "amount": i64()})
    p.process("acct_main", owner="acct", kernel=k.acct_main, config=cfg,
              start=p.on_created("acct"), messages={"credit": credit},
              on_message={"credit": k.C_CREDIT}, commands=k.ACCT_COMMANDS)
