"""Vegetable wholesale: one supermarket's vegetable sales, daily wholesale quotes and per-item
loss rates, 2020-07-01..2023-06-30 (CUMCM 2023 Problem C). Stage 1, schema only: the events are
ingested from the Spider2 tables (docs/research/spider2/veg.md).

Every REAL sits on an integer grid and travels as that integer: grams, jiao (0.1 RMB), fen
and basis points. POS lines keep the source `index` as `ord`, the order within a second that
no column explains. The `index` columns of the other tables are sort positions, rebuilt.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, amount, i64, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("categories", key="category_key", doc="Created by rule at the catalog start",
             cols={"ext_id": text(doc="category_code"), "category_name": text()})
    p.entity("items", key="item_key", doc="Created at its first wholesale quote (a rule)",
             cols={"ext_id": text(doc="item_code, a 13-15 digit barcode"), "item_name": text(),
                   "category_key": ref("categories"),
                   "loss_rate_bp": i64(doc="loss_rate_% x 100; one figure for the period")})
    p.event("wholesale_price_quoted", doc="One per item and day, at 00:00 (a rule)",
            cols={"item_key": ref("items"), "price": amount("CNY", doc="Fen per kg")})
    line = {"item_key": ref("items"),
            "qty_g": i64(doc="Grams, signed as in the source"),
            "unit_price_jiao": i64(doc="0.1 RMB per kg"),
            "discount_pct": i64(doc="discount(%), always 1 here"),
            "src_index": i64(doc="Source `index`: the order among equal times")}
    p.event("item_sold", doc="A POS line with qty > 0", cols=line)
    p.event("item_returned", doc="A POS line with qty < 0, not linked to a sale", cols=line)
