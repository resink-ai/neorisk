"""NYC trees: the 2015 NYC Street Tree Census (one row per tree) and an ACS household-income
lookup by ZIP. Stage 1, schema only: the events are ingested from the Spider2 tables
(docs/research/spider2/trees.md); stage 2 adds the behavior.

Nothing in the source has a time: every tree, species and ZIP is created at T0 and surveyed
at N, both the rule 2015-01-01 00:00 UTC. A tree's fixed traits travel on its creation, what
the surveyor saw on its snapshot, and a ZIP's ACS estimates on its snapshot. borocode and state are rebuilt from boroname and a constant.
Spider2's injected copies (and two upstream repeats in income_trees) come back from
`source_row_duplicated`, one event per extra identical row.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, f64, i32, i64, opt, ref, text

SCHEMA_VERSION = 1

BOROUGHS = ("Manhattan", "Bronx", "Brooklyn", "Queens", "Staten Island")


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("species", key="species_key", doc="The 132 spc_latin ↔ spc_common pairs",
             cols={"ext_id": text(doc="spc_latin"), "spc_common": text()})
    p.entity("trees", key="tree_key", doc="A 2015 census tree; created at the rule time T0",
             cols={"ext_id": text(doc="tree_id"),
                   "idx": i64(doc="Source pandas index; also the snapshot ord"),
                   "species": opt(ref("species")), "address": text(),
                   "zipcode": i64(doc="83 = Central Park (00083 with its zeros lost)"),
                   "boroname": cat(*BOROUGHS), "nta_name": text(),
                   "latitude": f64(), "longitude": f64()})
    p.event("trees_snapshot", doc="What the census observed, at the rule time N",
            cols={"tree_id": ref("trees"), "tree_dbh": i32(doc="Inches; 0 for stumps"),
                  "stump_diam": i32(doc="Inches; 0 unless a stump"),
                  "status": cat("Alive", "Dead", "Stump"),
                  "health": opt(cat("Good", "Fair", "Poor"))})
    p.entity("zip_incomes", key="zip_key",
             doc="An NYC ZIP with an ACS income row; created at T0, its estimates a snapshot",
             cols={"ext_id": text(doc="zipcode")})
    p.event("zip_incomes_snapshot", doc="ACS household income estimates as of the extract, at N",
            cols={"zipcode": ref("zip_incomes"), "estimate_total": i64(), "moe_total": i64(),
                  "estimate_median_income": i64(doc="250 = top-coded 250,000+"),
                  "moe_median_income": i64(), "estimate_mean_income": i64(),
                  "moe_mean_income": i64()})
    p.event("source_row_duplicated",
            doc="Spider2 artefact or upstream repeat: one extra identical source row, at N",
            cols={"source_table": cat("trees", "income_trees"),
                  "ext_id": text(doc="tree_id or zipcode of the copied row"),
                  "src_rowid": i64(doc="The copy's source rowid")})
