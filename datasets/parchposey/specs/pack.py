"""Parch & Posey: a paper company selling standard, gloss and poster paper to large US
companies. Accounts visit the web site through a channel and place orders of three paper
quantities; each account has one sales rep, and each rep one region. Stage 1, schema only: the
events are ingested from the Spider2 tables (docs/research/spider2/parchposey.md).

Order money is not carried: every amount is the quantities times the unit prices in integer
cents (499, 749, 812), divided by 100 once in build.sql. The source order and event ids are
carried, because their order is not time order (two interleaved order series).

A rep's region, and an account's website, location, point of contact and sales rep, are
snapshot columns at N = 2017-01-02 00:02:40, the last order.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, f64, i64, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("region", key="region_key", doc="Created by rule at 2013-12-04",
             cols={"ext_id": text(doc="id"), "name": text()})
    p.entity("sales_reps", key="rep_key", doc="Created by rule at 2013-12-04",
             cols={"ext_id": text(doc="id"), "name": text()})
    p.entity("accounts", key="account_key", doc="Created at its first web visit (rule)",
             cols={"ext_id": text(doc="id"), "name": text()})
    p.event("web_visited",
            cols={"account_id": ref("accounts"), "web_event_id": i64(doc="Source id (event_id is the log's)"),
                  "channel": cat("direct", "facebook", "organic", "adwords", "banner",
                                 "twitter")})
    p.event("order_placed", doc="Money columns are functions of the three quantities",
            cols={"account_id": ref("accounts"), "order_id": i64(doc="Source id"),
                  "standard_qty": i64(), "gloss_qty": i64(), "poster_qty": i64()})
    p.event("sales_reps_snapshot", doc="State at N: the rep's region",
            cols={"rep_key": ref("sales_reps"), "region_id": ref("region")})
    p.event("accounts_snapshot", doc="State at N: website, location, point of contact, rep",
            cols={"account_key": ref("accounts"), "website": text(), "lat": f64(),
                  "long": f64(), "primary_poc": text(), "sales_rep_id": ref("sales_reps")})
