"""Owners creating owners creating owners: a -> b -> c, all in one step (D42, D44)."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack
from neorisk_simkit.spec.types import i32, ref

from . import kernels as k

PACK = "chain"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    a_n: int = 4
    live: int = 8


def define(p: Pack, cfg: Config) -> None:
    a = p.table("a", key="a_id", mutable=True, cols={"n": i32()})
    b = p.table("b", key="b_id", mutable=True, cols={"a_id": ref("a"), "w": i32()})
    c = p.table("c", key="c_id", mutable=True, cols={"b_id": ref("b"), "w": i32()})
    p.owner("a", table=a, max_live=cfg.a_n)
    p.owner("b", table=b, max_live=cfg.live)
    p.owner("c", table=c, max_live=cfg.live)
    p.population(a, n=cfg.a_n, initial=1.0)
    p.event("a_made", owner="a", cols={"a_id": ref("a"), "b_id": ref("b")})
    p.event("b_made", owner="b", cols={"b_id": ref("b"), "c_id": ref("c"), "w": i32()})
    p.event("c_drew", owner="c", cols={"c_id": ref("c"), "b_id": ref("b"), "w": i32(),
                                       "draw": i32()})
    p.process("a_main", owner="a", kernel=k.a_main, start=p.on_created("a"), commands=(0,))
    p.process("b_main", owner="b", kernel=k.b_main, start=p.on_created("b"), commands=(0,))
    p.process("c_main", owner="c", kernel=k.c_main, start=p.on_created("c"), commands=(0,))
