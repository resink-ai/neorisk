"""COVID-19 by state: one reported row of cumulative cases and deaths per state per day.
Stage 1, schema only: the events are ingested from the Spider2 table
(docs/research/spider2/modern_misc.md).

The data is pre-aggregated: no finer grain exists. The event carries the totals as reported,
not daily deltas, because the totals sometimes fall (reporting corrections). Spider2 prepended
10 copies of existing rows; they come back from `source_row_duplicated`, never by dropping
them. Stage 2 must not learn from that event type.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, i64, ts

SCHEMA_VERSION = 1

STATES = ("CO", "FL", "MA", "NC")


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.event("daily_totals_reported",
            doc="Cumulative totals as reported for one state-day; time = the report date",
            cols={"state": cat(*STATES), "total_cases": i64(doc="Cumulative; can fall"),
                  "total_deaths": i64(doc="Cumulative; can fall")})
    p.event("source_row_duplicated",
            doc="Spider2 artefact: one extra identical row of the source table (time N)",
            cols={"src_table": cat("statistics", doc="The sentinel owner"),
                  "date": ts(doc="The copied row's report date"), "state": cat(*STATES)})
