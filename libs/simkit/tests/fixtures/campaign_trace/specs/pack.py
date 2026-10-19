"""The §07 campaign trace: two base users and a bounty-hunter campaign claim from one pool."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import i64, opt, ref

from . import kernels as k

PACK = "campaign_trace"
SCHEMA_VERSION = 1
CLAIM_AT_S = 12 * 86_400 + 9 * 3_600 + 14 * 60          # day 12 09:14:00


@dataclass(frozen=True)
class Config:
    users: int = 2
    bonus: int = 2_000
    cap_claims: int = 4
    claim_at_s: int = CLAIM_AT_S


def define(p: Pack, cfg: Config) -> None:
    user = p.table("user", key="user_id", mutable=True, cols={"invited_by": opt(ref("user"))})
    p.owner("user", table=user, max_live=cfg.users)
    p.population(user, n=cfg.users, initial=1.0)
    p.expose_owner("user")
    pool = p.shard("pool", key="pool_id", n=1, items=None,
                   state={"remaining": "i64", "granted": "i64"},
                   init=std.capped_pool.init(cfg.bonus * cfg.cap_claims))
    claim = p.request("claim", frm="user", to=pool, payload={"who": ref("user"), "amount": i64()},
                      response_payload={"amount": i64()}, responses=("granted", "rejected"),
                      latency=dist.constant(ms=500))
    p.message("refund", frm="user", to=pool, payload={"who": ref("user"), "amount": i64()},
              latency=dist.constant(ms=500))                  # gives a late grant back (F-35)
    u = {"user_id": ref("user")}
    p.event("order_placed", owner="user", cols={**u, "amount": i64()})
    p.event("bonus_paid", owner="user", cols={**u, "amount": i64()})
    p.event("bonus_granted", shard="pool", cols={"who": ref("user"), "amount": i64()})
    p.event("bonus_rejected", shard="pool", cols={"who": ref("user"), "amount": i64()})
    p.event("bonus_refunded", shard="pool", cols={"who": ref("user"), "amount": i64()})
    p.process("user_main", owner="user", kernel=k.user_main, config=cfg,
              start=p.on_created("user"), requests={"claim": claim},
              on_response={("claim", "granted"): k.R_OK, ("claim", "rejected"): k.R_NO},
              commands=k.USER_COMMANDS)
    p.process("pool_desk", shard="pool", kernel=k.pool_desk, on_request={"claim": k.C_CLAIM},
              on_message={"refund": k.C_REFUND}, commands=(k.C_CLAIM, k.C_REFUND))
    p.expose(first_order=k.first_order, pay_bonus=k.pay_bonus,
             claim=std.request("claim", who=std.actor(), amount=cfg.bonus,
                               store={"amount": "paid"},
                               release=std.send("refund", who=std.actor(),
                                                amount=std.field("paid"))))
