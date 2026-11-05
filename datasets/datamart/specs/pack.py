"""Data Mart: an online supermarket's weekly sales, pre-aggregated per (week, region, platform,
segment, customer type). Stage 1, schema only: the events are ingested from the Spider2 tables
(docs/research/spider2/datamart.md); stage 2 adds the behavior.

There is no finer grain than the weekly cell, so each cell is one reported event at its week's
Monday. cleaned_weekly_sales is derived from the same events in build.sql.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, amount, cat, i64, opt

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.event("weekly_sales_reported",
            doc="One pre-aggregated cell: a week's totals for (region, platform, segment, "
                "customer_type); no finer grain exists",
            cols={"region": cat("AFRICA", "ASIA", "CANADA", "EUROPE", "OCEANIA",
                                "SOUTH AMERICA", "USA"),
                  "platform": cat("Retail", "Shopify"),
                  "segment": opt(cat("C1", "C2", "C3", "C4", "F1", "F2", "F3",
                                     doc="NULL for every Guest cell")),
                  "customer_type": cat("New", "Existing", "Guest"),
                  "transactions": i64(min=0),
                  "sales": amount("USD", doc="Minor units; the source has whole dollars")})
