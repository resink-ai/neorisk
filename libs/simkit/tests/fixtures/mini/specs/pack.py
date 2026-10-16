"""Mini pack: a test fixture that touches every S1 engine path at tiny scale."""

from dataclasses import dataclass, field

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import amount, cat, i32, opt, ref

from . import kernels as k

PACK = "mini"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Behavior:
    ping_gap: dist.Dist = dist.exp(mean_s=3600)
    take_p: float = 0.3
    note_p: float = 0.2
    max_pings: int = 50


@dataclass(frozen=True)
class Config:
    users: int = 200
    max_live: int = 0                  # 0 = users; tests lower it to hit the live-state cap
    items: int = 40
    bins: int = 4
    behavior: Behavior = field(default_factory=Behavior)


def define(p: Pack, cfg: Config) -> None:
    item = p.table("item", key="item_id", cols={"bin": i32(), "price": amount(asset="USD")},
                   source=std.generated(n=cfg.items, cols={
                       "bin": dist.uniform_int(0, cfg.bins - 1),
                       "price": dist.uniform_int(100, 5_000)}))
    user = p.table("user", key="user_id", mutable=True, cols={
        "tier": cat("a", "b"), "balance": amount(asset="USD"), "last_note": opt(ref("note"))})
    p.table("note", key="note_id", mutable=True, child_of="user", cols={"size": i32()})
    p.ids("visit")
    p.owner("user", table=user, max_live=cfg.max_live or cfg.users)
    p.population(user, n=cfg.users, initial=0.5,
                 arrivals=dist.poisson_daily(weekly=(1, 1, 1, 1, 1, 1, 1)),
                 attrs={"tier": dist.categorical({"a": 0.5, "b": 0.5})})
    bins = p.shard("bin", key="bin", n=cfg.bins, items=item, state={"on_hand": "i32[item]"},
                   init={"on_hand": dist.uniform_int(0, 3)})
    take = p.request("take", frm="user", to=bins, payload={"item_id": ref("item")},
                     response_payload={"item_id": ref("item")}, responses=("ok", "none"),
                     latency=dist.constant(ms=200))
    p.event("user_joined", owner="user", cols={"user_id": ref("user"), "tier": cat("a", "b")})
    p.event("ping", owner="user", cols={
        "user_id": ref("user"), "visit_id": ref("visit"), "n": i32(min=0),
        "note_id": opt(ref("note"))})
    p.event("took", owner="user", cols={
        "user_id": ref("user"), "item_id": ref("item"), "ok": cat("yes", "no")})
    p.event("item_taken", shard="bin", cols={
        "bin": i32(), "item_id": ref("item"), "left": i32(min=0)})
    p.event("take_failed", shard="bin", cols={"bin": i32(), "item_id": ref("item")})
    p.process("user_main", owner="user", kernel=k.user_main, config=cfg.behavior,
              start=p.on_created("user"), requests={"take": take},
              on_response={("take", "ok"): k.R_OK, ("take", "none"): k.R_NONE},
              reads={"item": item}, commands=k.USER_COMMANDS)
    p.process("bin_desk", shard=bins, kernel=k.bin_desk, on_request={"take": k.C_TAKE},
              reads={"item": item})
