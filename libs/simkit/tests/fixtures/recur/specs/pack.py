"""Bounded recursion of created owners (D72): a node creates a child node until `levels`."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack
from neorisk_simkit.spec.types import i32, ref

from . import kernels as k

PACK = "recur"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    seeds: int = 2
    levels: int = 3
    max_depth: int = 3


def define(p: Pack, cfg: Config) -> None:
    seed = p.table("seed", key="seed_id", mutable=True, cols={"n": i32()})
    node = p.table("node", key="node_id", mutable=True, cols={"level": i32()})
    p.owner("seed", table=seed, max_live=cfg.seeds)
    p.owner("node", table=node, max_live=cfg.seeds * (cfg.levels + 1))
    p.population(seed, n=cfg.seeds, initial=1.0)
    p.event("grown", owner="node", cols={"node_id": ref("node"), "level": i32()})
    p.process("plant", owner="seed", kernel=k.plant, config=cfg, start=p.on_created("seed"))
    p.process("grow", owner="node", kernel=k.grow, config=cfg, start=p.on_created("node"),
              max_spawn_depth=cfg.max_depth)
