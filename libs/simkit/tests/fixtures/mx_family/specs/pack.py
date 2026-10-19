"""Spawn, join, repeat and until on one owner (D69, D70): a mother spawns `brood` chicks,
joins on their first call, then feeds once per minute until every chick is fed."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import i32, ref

from . import kernels as k

PACK = "mx_family"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    nests: int = 4
    brood_lo: int = 0
    brood_hi: int = 2
    wait: str = "20m"                 # the join's timeout
    max_rounds: int = 10
    recurse_p: float = 0.0            # 1.0: every chick spawns a chick (depth limit test)
    chick_slots: int = 8
    stagger_s: float = 0.0            # > 0: chicks hatch one per stagger (structural)
    recall_s: float = 600.0           # a chick's second call after its first


def define(p: Pack, cfg: Config) -> None:
    nest = p.table("nest", key="nest_id", mutable=True, cols={"brood": i32()})
    p.owner("nest", table=nest, max_live=cfg.nests)
    p.population(nest, n=cfg.nests, initial=1.0,
                 attrs={"brood": dist.uniform_int(cfg.brood_lo, cfg.brood_hi)})
    nid = {"nest_id": ref("nest")}
    p.event("fed", owner="nest", cols={**nid, "meal": i32()})
    p.event("called", owner="nest", cols={**nid, "chick": i32()})
    mother = p.machine("mother", owner="nest", start=p.on_created("nest"), initial="laying",
                       config=cfg, fields={"meals": "i32"})
    mother.state("laying", branch={
        "waiting": (1.0, dist.constant(s=60), std.spawn(
        "chick", n=std.col("brood"),
        stagger=dist.constant(s=cfg.stagger_s) if cfg.stagger_s else None))})
    mother.state("waiting", join={"feeding": "hungry"}, timer={"timeout": cfg.wait},
                 late="count")
    mother.state("feeding", repeat=(dist.constant(s=60), 1.0, k.feed),
                 max_repeats=cfg.max_rounds,
                 until=std.cond.ge(std.field("meals"), std.col("brood")), then="full")
    mother.final("full", "timeout")
    chick = p.machine("chick", owner="nest", initial="growing", max_instances=cfg.chick_slots,
                      max_spawn_depth=3)
    chick.state("growing", branch={"calling": (
        1.0, dist.constant(s=300),
        std.emit("called", nest_id=std.actor(), chick=1).then(std.send_parent("hungry")))},
        spawn={"chick": (cfg.recurse_p, dist.constant(s=1), dist.uniform_int(1, 1))})
    chick.state("calling", branch={"done": (1.0, dist.constant(s=cfg.recall_s),
                                            std.send_parent("hungry"))})
    chick.final("done")
