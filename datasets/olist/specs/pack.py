"""Olist: a Brazilian marketplace's orders (placed, approved, handed to the carrier,
delivered, reviewed) and its seller-acquisition funnel (leads qualified, deals won).
Stage 1, schema only: the events are ingested from the Spider2 tables
(docs/research/spider2/olist.md, events E1–E12, snapshots S1–S4); stage 2 adds the behavior.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, amount, cat, f64, i64, opt, ref, text, ts

SCHEMA_VERSION = 1

STATUSES = ("approved", "canceled", "created", "delivered", "invoiced", "processing", "shipped",
            "unavailable")
PAYMENT_TYPES = ("boleto", "credit_card", "debit_card", "not_defined", "voucher")


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("sellers", key="seller_key", doc="Sellers (S1); the address is a snapshot",
             cols={"ext_id": text(doc="Source seller_id")})
    p.entity("products", key="product_key",
             doc="Products (S2); listing text lengths, photos and measures are a snapshot",
             cols={"ext_id": text(doc="Source product_id"), "category": opt(text())})
    p.event("sellers_snapshot", doc="A seller's address as of the extract, at N",
            cols={"seller_id": ref("sellers"), "zip_code_prefix": i64(), "city": text(),
                  "state": text()})
    p.event("products_snapshot",
            doc="A listing as of the extract, at N; the source spells 'lenght'",
            cols={"product_id": ref("products"), "name_length": opt(f64()),
                  "description_length": opt(f64()), "photos_qty": opt(f64()),
                  "weight_g": opt(f64()), "length_cm": opt(f64()), "height_cm": opt(f64()),
                  "width_cm": opt(f64())})
    p.entity("geolocation", key="geo_key", doc="Zip-prefix coordinates (S3), verbatim with "
             "duplicates", cols={"ext_id": text(doc="Source rowid"), "zip_code_prefix": i64(),
                                 "lat": f64(), "lng": f64(), "city": text(), "state": text()})
    p.entity("translations", key="translation_key", doc="Category names in English (S4)",
             cols={"ext_id": text(doc="Portuguese category name"), "english": text()})

    p.event("lead_qualified", doc="E1: a marketing-qualified seller lead (first contact day)",
            cols={"mql_id": text(), "landing_page_id": text(), "origin": opt(text())})
    p.event("lead_won", doc="E2: the lead signs; the seller may never sell in the window",
            cols={"mql_id": text(), "seller_ext_id": text(doc="Not always in sellers"),
                  "sdr_id": text(), "sr_id": text(), "business_segment": opt(text()),
                  "lead_type": opt(text()), "lead_behaviour_profile": opt(text()),
                  "has_company": opt(i64()), "has_gtin": opt(i64()),
                  "average_stock": opt(text()), "business_type": opt(text()),
                  "declared_product_catalog_size": opt(f64()),
                  "declared_monthly_revenue": f64()})
    p.event("order_placed", doc="E3: checkout; the buyer's address is per order",
            cols={"order_id": text(), "customer_id": text(doc="Per-order buyer id"),
                  "customer_unique_id": text(doc="The person"), "zip_code_prefix": i64(),
                  "city": text(), "state": text(),
                  "estimated_delivery": ts(doc="The delivery promise made at checkout")})
    p.event("order_line_added", doc="E4: one cart line (quantity is repeated lines)",
            cols={"order_id": text(), "order_item_id": i64(), "product_key": ref("products"),
                  "seller_key": ref("sellers"), "price": amount("BRL"),
                  "freight_value": amount("BRL")})
    p.event("payment_recorded", doc="E5: one payment of the order (vouchers split payments)",
            cols={"order_id": text(), "payment_sequential": i64(),
                  "payment_type": cat(*PAYMENT_TYPES), "payment_installments": i64(),
                  "payment_value": amount("BRL")})
    p.event("order_approved", doc="E6: payment approved", cols={"order_id": text()})
    p.event("seller_ship_deadline_set", doc="E7: the seller's deadline to hand over",
            cols={"order_id": text(), "seller_key": ref("sellers"),
                  "shipping_limit_date": ts()})
    p.event("order_handed_to_carrier", doc="E8", cols={"order_id": text()})
    p.event("order_delivered", doc="E9: delivered to the customer", cols={"order_id": text()})
    p.event("order_status_final", doc="E10: a status the timestamps do not imply; time "
            "invented (the last known stage)", cols={"order_id": text(),
                                                     "order_status": cat(*STATUSES)})
    p.event("review_requested", doc="E11: the satisfaction survey goes out",
            cols={"review_id": text(), "order_id": text()})
    p.event("review_answered", doc="E12: the customer answers",
            cols={"review_id": text(), "order_id": text(), "review_score": i64(),
                  "review_comment_title": opt(text()), "review_comment_message": opt(text())})
