"""US Congress legislators, 1789-2020: each member's terms in the House or Senate, as a start
and, once it has happened, an end. Stage 1, schema only: the events are ingested from the
Spider2 tables (docs/research/spider2/legislators.md); stage 2 adds the behavior.

The snapshot is N = 2020-05-22, the last past term end. The 537 terms still open at N carry
their scheduled end on the start event; every other end is a `term_ended` event. The source's
REAL ids and district/class hold only integers, so they travel as i64. `legislation_date_dim`
is a generated calendar (1917-01-01 .. 1999-12-31) and has no events.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, i32, i64, opt, ref, text, ts

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def t():
    return opt(text())


def define(p: Pack) -> None:
    p.entity("legislators", key="legislator_id",
             doc="Created at the first term start (a rule); biography and cross-reference ids",
             cols={"ext_id": text(doc="id_bioguide"), "full_name": text(),
                   "first_name": text(), "last_name": text(), "middle_name": t(),
                   "nickname": t(), "suffix": t(), "other_names_end": t(),
                   "other_names_last": t(), "birthday": opt(text(doc="YYYY-MM-DD, verbatim")),
                   "gender": cat("F", "M"), "id_bioguide_previous_0": t(),
                   "id_govtrack": i64(), "id_icpsr": opt(i64()), "id_wikipedia": t(),
                   "id_wikidata": t(), "id_google_entity_id": t(),
                   "id_house_history": opt(i64()), "id_house_history_alternate": opt(i64()),
                   "id_thomas": opt(i64()), "id_cspan": opt(i64()),
                   "id_votesmart": opt(i64()), "id_lis": t(), "id_ballotpedia": t(),
                   "id_opensecrets": t(), "id_fec_0": t(), "id_fec_1": t(), "id_fec_2": t()})
    p.event("term_started", doc="A term begins; ord = 2 * term_number",
            cols={"legislator_id": ref("legislators"), "term_number": i32(),
                  "term_type": cat("rep", "sen"), "state": text(),
                  "district": opt(i64(doc="House only; -1 and 0 are sentinels")),
                  "class": opt(i64(doc="Senate only")), "party": t(), "how": t(), "url": t(),
                  "address": t(), "phone": t(), "fax": t(), "contact_form": t(),
                  "office": t(), "state_rank": t(), "rss_url": t(), "caucus": t(),
                  "scheduled_end": opt(ts(doc="Only on the 537 terms still open at N"))})
    p.event("term_ended", doc="A term ends (statutory or early); ord = 2 * term_number + 1",
            cols={"legislator_id": ref("legislators"), "term_number": i32()})
