"""Per-item `ref` shard state that outlives its step (spec §12; S2 Task 1, D38).

One `acct` creates a `ticket` ID at start and stows it in rack shard 1 (of 2), in bin 3: the
shard's second item, CSR position 3 of the `held` array. Two hours later (a later step) the rack
echoes what that bin holds, so seal must remap the per-item range `offs[1]:offs[2]`.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import amount, i32, ref

from . import kernels as k

PACK = "rack"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    accts: int = 1


def define(p: Pack, cfg: Config) -> None:
    acct = p.table("acct", key="acct_id", mutable=True, cols={"bal": amount(asset="USD")})
    bin_ = p.table("bin", key="bin_id", cols={"rack": i32()}, source=std.rows(rack=[0, 0, 1, 1]))
    p.ids("ticket")
    p.owner("acct", table=acct, max_live=cfg.accts)
    p.population(acct, n=cfg.accts, initial=1.0)
    rack = p.shard("rack", key="rack", n=2, items=bin_, state={"held": "ref[bin]"})
    stow = p.message("stow", frm="acct", to=rack,
                     payload={"ticket": ref("ticket"), "bin_id": ref("bin")},
                     latency=dist.constant(ms=10))
    p.event("opened", owner="acct", cols={"acct_id": ref("acct"), "ticket_id": ref("ticket")})
    p.event("stowed", shard="rack", cols={"ticket_id": ref("ticket"), "bin_id": ref("bin")})
    p.event("echoed", shard="rack", cols={"held_id": ref("ticket")})
    p.process("acct_main", owner="acct", kernel=k.acct_main, start=p.on_created("acct"),
              messages={"stow": stow}, commands=(0,))
    p.process("rack_main", shard=rack, kernel=k.rack_main, on_message={"stow": k.C_STOW},
              reads={"bin": bin_}, commands=k.RACK_COMMANDS)
