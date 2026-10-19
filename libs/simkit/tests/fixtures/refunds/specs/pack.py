"""sum_le with a state column on the right (F-07, D81)."""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, dist, law
from neorisk_simkit.spec.types import i64, ref

from . import kernels as k

PACK = "refunds"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Config:
    extra: int = 0                    # 1: the second refund exceeds the order amount


def define(p: Pack, cfg: Config) -> None:
    order = p.table("order", key="order_id", mutable=True, cols={"amount": i64()})
    p.owner("order", table=order, max_live=3)
    p.population(order, n=3, initial=1.0, attrs={"amount": dist.uniform_int(100, 300)})
    p.event("refund_issued", owner="order", cols={"order_id": ref("order"), "amount": i64()})
    p.process("order_main", owner="order", kernel=k.order_main, config=cfg,
              start=p.on_created("order"), commands=k.ORDER_COMMANDS)
    p.check("chk.refund_le_paid",
            law.sum_le("refund_issued.amount", "order.amount", by="order_id"), required=True)
