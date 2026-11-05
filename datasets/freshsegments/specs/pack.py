"""Fresh Segments: an ad-tech firm's interest taxonomy and each interest's monthly audience
metrics (composition and index). Stage 1, schema only: the events are ingested from the Spider2
tables (docs/research/spider2/freshsegments.md); stage 2 adds the behavior.

ranking, percentile_ranking, _month and _year are derived in build.sql. 1,194 metric rows have
no month (1,193 of them no interest either): they are stamped at N, and their owner is the
sentinel 'none'. An interest's name and summary are snapshot columns at N: 709 interests were
edited after creation (interest_modified), and the edit is not recorded.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, f64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("interests", key="interest_key", doc="interest_map; created_at is the source's own",
             cols={"ext_id": text(doc="Source id")})
    p.event("interest_modified", doc="last_modified, when later than created_at; what changed "
                                     "is unknown",
            cols={"interest_key": ref("interests")})
    p.event("interest_metrics_reported",
            doc="One interest's metrics for a month, at the first day of the next month; "
                "month-less rows at N",
            cols={"interest": text(doc="Owner: the source interest id, or the sentinel "
                                       "'none' when it is NULL"),
                  "interest_key": opt(ref("interests")),
                  "month_year": opt(text(doc="MM-YYYY, verbatim; NULL for 1,194 rows")),
                  "composition": f64(), "index_value": f64()})
    p.event("interests_snapshot", doc="State at N: the name and summary",
            cols={"interest_key": ref("interests"), "interest_name": text(),
                  "interest_summary": opt(text(doc="Verbatim; 4 end in a space"))})
