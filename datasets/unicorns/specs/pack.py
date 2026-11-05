"""Unicorn companies: each company joins the list on its unicorn date; its valuation, funding
and investors are values as of the list's date. Stage 1, schema only: the events are ingested
from the Spider2 tables (docs/research/spider2/unicorns.md).

Spider2 prepended 11 copies of existing rows to each table, a different company set per
table. They come back from `source_row_duplicated`, never by dropping them: local049's
accepted `_a` answer depends on them. Stage 2 must not learn from that event type.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, i32, i64, opt, ref, text

SCHEMA_VERSION = 1

INDUSTRIES = (
    '"Supply chain, logistics, & delivery"', "Artificial intelligence",
    "Auto & transportation", "Consumer & retail", "Cybersecurity",
    "Data management & analytics", "E-commerce & direct-to-consumer", "Edtech", "Fintech",
    "Hardware", "Health", "Internet software & services", "Mobile & telecommunications",
    "Other", "Travel")


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("companies", key="company_key",
             doc="A unicorn; created_at = date_joined (natural, midnight)",
             cols={"ext_id": text(doc="Source company_id"),
                   "industry": cat(*INDUSTRIES, doc="Verbatim, the quoted label included"),
                   "year_founded": i32(doc="A year only; once later than the join")})
    p.event("companies_snapshot",
            doc="As-of-N values (a rule time): current valuation, lifetime funding, investors",
            cols={"company_id": ref("companies"), "valuation": i64(doc="Whole dollars"),
                  "funding": i64(doc="Whole dollars; 0 = unknown in the source"),
                  "select_investors": opt(text(doc="Verbatim, CSV-quoted when it has a comma"))})
    p.event("source_row_duplicated",
            doc="Spider2 artefact: one extra identical row in one source table (time N)",
            cols={"company_id": ref("companies"),
                  "src_table": cat("companies_funding", "companies_dates",
                                   "companies_industries")})
