"""AtliQ Hardware: a computer-hardware maker selling to retailers, distributors and its own
stores. Sales are reported as monthly totals per (product, customer); prices, manufacturing
costs and customer pre-invoice discounts are set once per fiscal year (September start).
Stage 1, schema only: the events are ingested from the Spider2 tables
(docs/research/spider2/atliq.md).

Prices, costs and discount rates have at most 4 decimals, so they travel as integers of
1e-4 units and are divided back in build.sql. `fiscal_year` of a sale is derived from its month.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, i32, i64, opt, ref, text

SCHEMA_VERSION = 1

SCALE = "1e-4 units: value = n / 10000"


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("customers", key="customer_key", doc="Created by rule at 2019-09-01",
             cols={"ext_id": text(doc="customer_code"), "customer": text(),
                   "platform": cat("Brick & Mortar", "E-Commerce"),
                   "channel": cat("Direct", "Distributor", "Retailer"), "market": text(),
                   "sub_zone": opt(text()), "region": opt(text())})
    p.entity("products", key="product_key",
             doc="Created at its first priced fiscal year's start, else 2019-09-01 (rule)",
             cols={"ext_id": text(doc="product_code"), "division": cat("N & S", "P & A", "PC"),
                   "segment": text(), "category": text(), "product": text(),
                   "variant": text()})
    p.event("product_priced", doc="A product's gross price and manufacturing cost for a fiscal "
            "year; the time is the fiscal year's start (rule)",
            cols={"product_id": ref("products"), "fiscal_year": i32(),
                  "gross_price": i64(doc=SCALE), "manufacturing_cost": i64(doc=SCALE)})
    p.event("customer_deduction_set", doc="A customer's pre-invoice discount for a fiscal "
            "year; the time is the fiscal year's start (rule)",
            cols={"customer_id": ref("customers"), "fiscal_year": i32(),
                  "pre_invoice_discount_pct": i64(doc=SCALE)})
    p.event("monthly_sales_reported", doc="Pre-aggregated: one row per month x product x "
            "customer, at the month's first day",
            cols={"customer_id": ref("customers"), "product_id": ref("products"),
                  "sold_quantity": i64()})
