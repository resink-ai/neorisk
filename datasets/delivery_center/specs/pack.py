"""Delivery Center: orders from stores in delivery hubs, through production, collection,
expedition and delivery by drivers, with split payments. Stage 1, schema only: the events
are ingested from the Spider2 tables (docs/research/spider2/delivery_center.md); stage 2 adds
the behavior.

Payments and deliveries have no time in the source: a payment is stamped at its order's
creation, a delivery at its order's `delivering` moment (else the latest earlier one), and
the close of an order at `finished` (else its last moment). The source's `order_metric_*`
values are not a function of the moments (about 25% are off by up to 1.2 s), so they are
carried on `order_closed`, as are the `order_created_*` parts (wrong on 3 rows).
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, amount, cat, f64, i64, opt, ref, text

SCHEMA_VERSION = 1

STAGES = ("accepted", "ready", "collected", "in_expedition", "delivering", "delivered",
          "finished")
METHODS = ("BANK_TRANSFER_DC", "CREDIT", "CREDIT_STORE", "DEBIT", "DEBIT_STORE",
           "INSTALLMENT_CREDIT_STORE", "MEAL_BENEFIT", "MONEY", "ONLINE", "PAYMENT_LINK",
           "STORE_DIRECT_PAYMENT", "VOUCHER", "VOUCHER_DC", "VOUCHER_OL", "VOUCHER_STORE")
METRICS = ("collected_time", "paused_time", "production_time", "walking_time",
           "expediton_speed_time", "transit_time", "cycle_time")


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("hubs", key="hub_key", doc="Delivery hubs",
             cols={"ext_id": text(doc="Source hub_id"), "hub_name": text(), "hub_city": text(),
                   "hub_state": text(), "hub_latitude": f64(), "hub_longitude": f64()})
    p.entity("stores", key="store_key",
             doc="Stores; each sits in one hub; plan price and coordinates are a snapshot",
             cols={"ext_id": text(doc="Source store_id"), "hub_key": ref("hubs"),
                   "store_name": text(doc="Byte-exact: some have trailing spaces"),
                   "store_segment": text()})
    p.entity("channels", key="channel_key", doc="Sales channels",
             cols={"ext_id": text(doc="Source channel_id"), "channel_name": text(),
                   "channel_type": text()})
    p.entity("drivers", key="driver_key", doc="Drivers; modal and type are a snapshot",
             cols={"ext_id": text(doc="Source driver_id")})
    p.event("stores_snapshot", doc="A store's plan price and coordinates as of the extract, at N",
            cols={"store_key": ref("stores"), "store_plan_price": opt(f64()),
                  "store_latitude": opt(f64()), "store_longitude": opt(f64())})
    p.event("drivers_snapshot", doc="A driver's modal (biker, motoboy) and type (freelance, "
            "logistic operator) as of the extract, at N",
            cols={"driver_key": ref("drivers"), "driver_modal": text(), "driver_type": text()})

    p.event("order_created", doc="A store receives an order",
            cols={"order_id": i64(doc="Source order_id"), "store_key": ref("stores"),
                  "channel_key": ref("channels"), "order_amount": amount("BRL"),
                  "order_delivery_fee": amount("BRL"),
                  **{f"order_created_{k}": i64(doc="Carried: wrong on 3 rows in the source")
                     for k in ("hour", "minute", "day", "month", "year")}})
    p.event("order_stage", doc="The order reaches a stage (one per non-null source moment; "
            "1.24% of orders reach them out of order)",
            cols={"order_id": i64(), "stage": cat(*STAGES), "stage_no": i64(doc="1..7")})
    p.event("order_closed", doc="Finished or canceled; carries the source's metrics",
            cols={"order_id": i64(), "order_status": cat("FINISHED", "CANCELED"),
                  "order_delivery_cost": opt(amount("BRL")),
                  **{f"order_metric_{m}": opt(f64(doc="Minutes, as in the source"))
                     for m in METRICS}})
    p.event("payment_recorded", doc="One payment of the order (13.9% split, often + voucher)",
            cols={"payment_id": i64(), "order_id": i64(), "payment_amount": amount("BRL"),
                  "payment_fee": opt(amount("BRL")), "payment_method": cat(*METHODS),
                  "payment_status": cat("AWAITING", "CHARGEBACK", "PAID")})
    p.event("delivery_assigned", doc="A delivery leg for the order (driver may be unknown)",
            cols={"delivery_id": i64(), "order_id": i64(), "driver_key": opt(ref("drivers")),
                  "delivery_distance_meters": opt(f64())})
    p.event("delivery_closed", doc="The leg ends; open (DELIVERING) legs have none",
            cols={"delivery_id": i64(), "order_id": i64(),
                  "delivery_status": cat("DELIVERED", "CANCELLED")})
