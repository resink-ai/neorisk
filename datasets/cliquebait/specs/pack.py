"""Clique Bait: an online seafood shop's click log (page views, cart adds, purchases, ad
impressions and clicks). Stage 1, schema only: the source table already is an event log
(docs/research/spider2/bank_clicklog.md, part B); stage 2 adds the behavior.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, f64, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("cookies", key="cookie_key", doc="A browser cookie; a user may own several",
             cols={"ext_id": text(doc="Source cookie_id"), "user_id": i64(doc="Source user_id")})
    p.entity("pages", key="page_key", doc="Site pages; product pages carry a product",
             cols={"ext_id": text(doc="Source page_id"), "page_name": text(),
                   "product_category": opt(text()), "product_id": opt(f64())})
    p.entity("event_kinds", key="event_kind_key", doc="Page View, Add to Cart, Purchase, ...",
             cols={"ext_id": text(doc="Source event_type"), "event_name": text()})
    p.entity("campaigns", key="campaign_key", doc="Marketing campaigns (dates kept as text)",
             cols={"ext_id": text(doc="Source campaign_id"), "products": text(),
                   "campaign_name": text(), "start_date": text(), "end_date": text()})
    p.event("page_event", doc="One click-log row; a purchase means the whole cart of the visit",
            cols={"visit_id": text(), "cookie_key": ref("cookies"), "page_key": ref("pages"),
                  "event_kind_key": ref("event_kinds"),
                  "sequence_number": i64(doc="Rank by time within the visit")})
