"""Overlay API fixture: a base pack with an exposed owner, exposed actions and a capped pot
that base users and overlay members both claim from."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import cat, i64, opt, ref, ts

from . import kernels as k

PACK = "ring"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    users: int = 6
    pot: int = 5_000
    bonus: int = 1_000


def define(p: Pack, cfg: Config) -> None:
    device = p.table("device", key="device_id", doc="Devices", cols={
        "os": cat("ios", "android", "windows", "macos", "linux"),
        "kind": cat("phone", "tablet", "desktop"), "first_seen": ts()})
    user = p.table("user", key="user_id", mutable=True,
                   cols={"tier": cat("a", "b"), "invited_by": opt(ref("user"))})
    p.owner("user", table=user, max_live=cfg.users)
    p.population(user, n=cfg.users, initial=1.0,
                 attrs={"tier": dist.categorical({"a": 0.5, "b": 0.5})},
                 refs={"device": std.devices(per_user=dist.categorical({1: 1.0}), table=device,
                                             share=0.0)})
    p.expose_owner("user")
    pot = p.shard("pot", key="pot_id", n=1, items=None,
                  state={"remaining": "i64", "granted": "i64"},
                  init=std.capped_pool.init(cfg.pot))
    claim = p.request("claim", frm="user", to=pot, payload={"who": ref("user"), "amount": i64()},
                      response_payload={"amount": i64()}, responses=("granted", "rejected"),
                      latency=dist.constant(ms=500))
    p.message("refund", frm="user", to=pot, payload={"who": ref("user"), "amount": i64()},
              latency=dist.constant(ms=500))                  # gives a late grant back (F-35)
    u = {"user_id": ref("user")}
    p.event("signed_up", owner="user", cols={**u, "device_id": ref("device"),
                                             "invited_by": opt(ref("user"))})
    p.event("bonus_paid", owner="user", cols={**u, "amount": i64()})
    # `sender`: the raw `cmd.sender` of the claim (the requesting owner's dense id), so a test
    # can tell which owner sent it (contracts: Tasks 3/8 -> 10)
    p.event("granted", shard="pot", cols={"who": ref("user"), "amount": i64(),
                                          "sender": i64()})
    p.event("refused", shard="pot", cols={"who": ref("user"), "amount": i64(),
                                          "sender": i64()})
    p.event("refunded", shard="pot", cols={"who": ref("user"), "amount": i64()})
    p.process("user_main", owner="user", kernel=k.user_main, config=cfg,
              start=p.on_created("user"), requests={"claim": claim},
              on_response={("claim", "granted"): k.R_OK, ("claim", "rejected"): k.R_NO},
              refs={"device": "device"}, commands=k.USER_COMMANDS)
    p.process("pot_desk", shard="pot", kernel=k.pot_desk, on_request={"claim": k.C_CLAIM},
              on_message={"refund": k.C_REFUND}, commands=(k.C_CLAIM, k.C_REFUND))
    p.expose(signup=k.signup, signup_invited=k.signup_invited, pay_bonus=k.pay_bonus,
             claim=std.request("claim", who=std.actor(), amount=cfg.bonus,
                               store={"amount": "paid"},
                               release=std.send("refund", who=std.actor(),
                                                amount=std.field("paid"))))
    p.expose_param("bonus", cfg.bonus)
