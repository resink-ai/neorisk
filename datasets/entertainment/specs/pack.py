"""entertainment: the Entertainment Agency of *SQL Queries for Mere Mortals* (Viescas and
Hernandez). Agents book entertainers (acts with members and ranked styles) for customers
(with ranked style preferences). Stage 1, schema only: the events are ingested from the
Spider2 tables (docs/research/spider2/entertainment.md); stage 2 adds the behavior.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, f64, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("agents", key="agent_id", doc="Created at DateHired",
             cols={"ext_id": text(), "first_name": opt(text()), "last_name": opt(text()),
                   "street_address": opt(text()), "city": opt(text()), "state": opt(text()),
                   "zip": opt(text()), "phone": opt(text()),
                   "salary": opt(i64(doc="whole dollars")), "commission_rate": opt(f64())})
    p.entity("entertainers", key="entertainer_id", doc="Created at DateEntered",
             cols={"ext_id": text(), "stage_name": opt(text()), "ssn": opt(text()),
                   "street_address": opt(text()), "city": opt(text()), "state": opt(text()),
                   "zip": opt(text()), "phone": opt(text()), "web_page": opt(text()),
                   "email": opt(text())})
    p.entity("members", key="member_id",
             doc="Created at the earliest DateEntered of their entertainers (a rule)",
             cols={"ext_id": text(), "first_name": opt(text()), "last_name": opt(text()),
                   "phone": opt(text()), "gender": opt(text())})
    p.entity("entertainer_members", key="em_id", doc="Created at the entertainer's DateEntered",
             cols={"ext_id": text(doc="'<EntertainerID>/<MemberID>'"),
                   "entertainer_id": ref("entertainers"), "member_id": ref("members"),
                   "status": opt(i64())})
    p.entity("musical_styles", key="style_id", doc="Created at T0 = 1995-01-20 (a rule)",
             cols={"ext_id": text(), "style_name": opt(text())})
    p.entity("entertainer_styles", key="es_id", doc="Created at the entertainer's DateEntered",
             cols={"ext_id": text(doc="'<EntertainerID>/<StyleID>'"),
                   "entertainer_id": ref("entertainers"), "style_id": ref("musical_styles"),
                   "style_strength": i64()})
    p.entity("customers", key="customer_id",
             doc="Created at their first engagement's start; the 2 with none at T0 (rules)",
             cols={"ext_id": text(), "first_name": opt(text()), "last_name": opt(text()),
                   "street_address": opt(text()), "city": opt(text()), "state": opt(text()),
                   "zip": opt(text()), "phone": opt(text())})
    p.entity("musical_preferences", key="mp_id", doc="Created with their customer",
             cols={"ext_id": text(doc="'<CustomerID>/<StyleID>'"),
                   "customer_id": ref("customers"), "style_id": ref("musical_styles"),
                   "preference_seq": i64()})
    p.event("engagement_booked",
            doc="At the performance start: the booking time is unknown (a rule)",
            cols={"customer_id": ref("customers"), "engagement_number": i64(),
                  "entertainer_id": ref("entertainers"), "agent_id": ref("agents"),
                  "end_date": text(doc="'YYYY-MM-DD'"),
                  "stop_time": text(doc="'HH:MM:SS'; at or after midnight in 17 rows"),
                  "contract_price": i64(doc="whole dollars")})
