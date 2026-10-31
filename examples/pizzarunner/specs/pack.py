"""Pizza Runner: customers order pizzas, runners pick the order up and deliver it, or it is
cancelled. Stage 1, schema only: the events are ingested from the Spider2 tables
(docs/research/spider2/pizzarunner.md); stage 2 adds the behavior.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("runners", key="runner_id", doc="Delivery runners; created at registration",
             cols={"ext_id": text(doc="Source runner_id")})
    p.entity("pizzas", key="pizza_id", doc="The menu",
             cols={"ext_id": text(doc="Source pizza_id"), "pizza_name": text(),
                   "toppings": text(doc="Recipe: comma+space list of topping ids, verbatim")})
    p.entity("toppings", key="topping_id",
             cols={"ext_id": text(doc="Source topping_id"), "topping_name": text()})
    p.entity("customers", key="customer_id", doc="Created at their first order",
             cols={"ext_id": text(doc="Source customer_id")})
    p.event("pizza_ordered", doc="One pizza line of an order",
            cols={"order_id": i64(), "customer_id": ref("customers"), "pizza_id": ref("pizzas"),
                  "exclusions": opt(text(doc="Comma list, no spaces, verbatim")),
                  "extras": opt(text(doc="Comma list, no spaces, verbatim")),
                  "src_row": i64(doc="Source rowid: the line order within an order")})
    p.event("order_picked_up", cols={"order_id": i64(), "runner_id": ref("runners")})
    p.event("order_delivered", doc="Time is pickup + duration minutes (a rule)",
            cols={"order_id": i64(), "runner_id": ref("runners"),
                  "distance": text(doc="Verbatim, e.g. '20km', '23.4 km'"),
                  "duration": text(doc="Verbatim, e.g. '32 minutes'")})
    p.event("order_cancelled", doc="Time is the order's time (a rule); a runner was assigned",
            cols={"order_id": i64(), "runner_id": ref("runners"),
                  "cancellation": cat("Restaurant Cancellation", "Customer Cancellation")})
