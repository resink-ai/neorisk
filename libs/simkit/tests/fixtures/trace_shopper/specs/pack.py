"""Spec §07: a recurring shopper buying two SKUs. Shards A, B, C hold 1, 0, 1 units."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, std
from neorisk_simkit.spec.types import amount, cat, i16, opt, ref

from . import kernels as k

PACK = "trace_shopper"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    spend_limit: int = 100
    hold: int = 80
    substitute_after_us: int = 129_700_000          # 10:00:00.3 -> 10:02:10.0


def define(p: Pack, cfg: Config) -> None:
    sku = p.table("sku", key="sku_id", cols={"sku_group": i16(), "label": cat("A", "B", "C")},
                  source=std.rows(sku_group=[0, 1, 2], label=["A", "B", "C"]))
    user = p.table("user", key="user_id", mutable=True, cols={
        "spend_limit": amount(asset="USD"), "hold": amount(asset="USD"),
        "spent": amount(asset="USD")})
    payment = p.table("payment", key="payment_id", mutable=True, cols={
        "user_id": ref("user"), "amount": amount(asset="USD")})
    p.ids("checkout")
    p.owner("user", table=user, max_live=1)
    p.owner("payment", table=payment, max_live=4)
    p.population(user, n=1, initial=1.0)
    inv = p.shard("inventory", key="sku_group", n=3, items=sku,
                  state={"on_hand": "i32[sku]", "reserved": "i32[sku]"},
                  init={"on_hand": [1, 0, 1]})
    lat = dist.constant(ms=300)
    line = {"sku_id": ref("sku")}
    reserve = p.request("reserve", frm="user", to=inv, payload=line, response_payload=line,
                        responses=("granted", "rejected"), latency=lat)
    release = p.message("release", frm="user", to=inv, payload=line, latency=lat)
    commit = p.message("commit", frm="user", to=inv, payload=line, latency=lat)
    u = {"user_id": ref("user"), "checkout_id": ref("checkout")}
    p.event("checkout_started", owner="user", cols={**u, "lines": i16(),
                                                    "hold_after": amount(asset="USD")})
    p.event("checkout_failed", owner="user", cols={
        **u, "reason": cat("out_of_stock"), "sku_id": opt(ref("sku")),
        "hold_after": amount(asset="USD")})
    p.event("checkout_succeeded", owner="user", cols={
        **u, "payment_id": ref("payment"), "spent_after": amount(asset="USD")})
    p.event("payment_created", owner="payment", cols={
        "payment_id": ref("payment"), "user_id": ref("user"), "amount": amount(asset="USD")})
    stock = {"sku_id": ref("sku"), "checkout_id": ref("checkout")}
    for name in ("stock_reserved", "stock_rejected", "stock_released", "stock_committed"):
        p.event(name, shard="inventory", cols=stock)
    p.process("journey", owner="user", kernel=k.journey, config=cfg,
              start=p.on_created("user"), requests={"reserve": reserve},
              messages={"release": release, "commit": commit},
              on_response={("reserve", "granted"): k.R_GRANTED,
                           ("reserve", "rejected"): k.R_REJECTED},
              reads={"sku": sku}, commands=k.JOURNEY_COMMANDS)
    p.process("payment_start", owner="payment", kernel=k.payment_start,
              start=p.on_created("payment"), commands=(0,))
    p.process("desk", shard=inv, kernel=k.desk, on_request={"reserve": k.C_RESERVE},
              on_message={"release": k.C_RELEASE, "commit": k.C_COMMIT}, reads={"sku": sku})
