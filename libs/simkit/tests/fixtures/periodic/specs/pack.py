"""A periodic shard process (D26): phase-spread first occurrence, jittered later ones."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import i32

from . import kernels as k

PACK = "periodic"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    shards: int = 3


def define(p: Pack, cfg: Config) -> None:
    clock = p.shard("clock", key="clock", n=cfg.shards, items=None, state={"ticks": "i32"})
    p.event("ticked", shard="clock", cols={"clock": i32(), "j": i32(), "n": i32()})
    p.process("tick", shard=clock, kernel=k.tick, every="2h", jitter=dist.exp(mean_s=60))
