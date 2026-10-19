"""Execution owners (D74): a crew owner acts for the user table — it emits user events, sends
the user's request and creates member rows of `user` without admitting them as owners."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist
from neorisk_simkit.spec.types import cat, i32, ref

from . import kernels as k

PACK = "crew"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    users: int = 3
    crews: int = 2
    initial: float = 1.0          # < 1: the rest arrive later (a gap in the ref range, D75)
    executors: bool = True        # False: the base pack alone (no crew partition, D75 test)


def define(p: Pack, cfg: Config) -> None:
    user = p.table("user", key="user_id", mutable=True, cols={"tier": cat("a", "b")})
    p.owner("user", table=user, max_live=cfg.users)
    p.population(user, n=cfg.users, initial=cfg.initial,
                 arrivals=dist.burst(start_day=0.01, span_days=1.0),
                 attrs={"tier": dist.categorical({"a": 0.5, "b": 0.5})})
    p.expose_owner("user")
    desk = p.shard("desk", key="desk", n=1, items=None, state={"asks": "i64"})
    ask = p.request("ask", frm="user", to=desk, payload={"who": ref("user")},
                    responses=("ok",), latency=dist.constant(ms=100))
    p.event("joined", owner="user", cols={"user_id": ref("user"), "tier": cat("a", "b")})
    p.event("asked", shard="desk", cols={"who": ref("user")})
    p.process("user_main", owner="user", kernel=k.user_main, start=p.on_created("user"),
              requests={"ask": ask}, on_response={("ask", "ok"): k.R_OK},
              commands=k.USER_COMMANDS)
    p.process("desk_main", shard=desk, kernel=k.desk_main, on_request={"ask": k.C_ASK})
    if not cfg.executors:
        return
    crew = p.table("crew", key="crew_id", mutable=True, cols={"size": i32()})
    p.owner("crew", table=crew, max_live=max(1, cfg.crews), acts_for="user")
    p.population(crew, n=cfg.crews, initial=1.0, attrs={"size": dist.uniform_int(2, 3)})
    p.process("crew_main", owner="crew", kernel=k.crew_main, start=p.on_created("crew"),
              requests={"ask": ask}, on_response={("ask", "ok"): k.R_OK},
              commands=k.CREW_COMMANDS)
