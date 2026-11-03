"""Data Bank: customers on a bank's storage nodes, and their ledger (deposits, purchases,
withdrawals). Stage 1, schema only: the events are ingested from the Spider2 tables
(docs/research/spider2/bank_clicklog.md, part A); stage 2 adds the behavior.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, amount, cat, i64, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("regions", key="region_id", doc="The five regions",
             cols={"ext_id": text(doc="Source region_id"), "region_name": text()})
    p.entity("customers", key="customer_id", doc="Bank customers; one region for life",
             cols={"ext_id": text(doc="Source customer_id"),
                   "region_id": ref("regions", doc="The customer's region")})
    p.event("account_opened", doc="A customer's first node assignment (their first day)",
            cols={"customer_id": ref("customers"), "node_id": i64(doc="Node within the region")})
    p.event("node_reassigned", doc="The customer's data moves to another node (maybe the same)",
            cols={"customer_id": ref("customers"), "node_id": i64(doc="Node within the region")})
    p.event("transaction_posted", doc="A ledger entry; no balance check (overdrafts happen)",
            cols={"customer_id": ref("customers"),
                  "txn_type": cat("deposit", "purchase", "withdrawal"),
                  "txn_amount": amount("USD", doc="Minor units; the source has whole dollars"),
                  "src_rowid": i64(doc="Source rowid: the order within a day")})
