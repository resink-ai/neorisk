"""Schema fixture: the order_placed event from spec section 14, no processes."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack
from neorisk_simkit.spec.types import amount, cat, i32, opt, ref, text

PACK = "ecommerce"
SCHEMA_VERSION = 7


@dataclass(frozen=True)
class Config:
    users: int = 10


def define(p: Pack, cfg: Config) -> None:
    user = p.table("user", key="user_id", mutable=True, cols={"tier": cat("a", "b")})
    p.table("sku", key="sku_id", cols={"price": amount(asset="USD")})
    p.table("order", key="order_id", mutable=True, child_of="user", cols={
        "amount": amount(asset="USD")})
    p.owner("user", table=user, max_live=cfg.users)
    p.population(user, n=cfg.users, initial=1.0)
    p.event("order_placed", owner="user", doc="A shopper submits a cart", cols={
        "order_id":    ref("order"),
        "user_id":     ref("user"),
        "sku_id":      ref("sku"),
        "quantity":    i32(min=1),
        "amount":      amount(asset="USD"),               # int64 minor units
        "channel":     cat("web", "app", "api"),
        "coupon_code": opt(text()),
    })
