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
    p.entity("agents", key="agent_id", doc="Hired at DateHired; contact and pay are a snapshot",
             cols={"ext_id": text(), "first_name": opt(text()), "last_name": opt(text())})
    p.entity("entertainers", key="entertainer_id",
             doc="Registered at DateEntered; contact details are a snapshot",
             cols={"ext_id": text(), "stage_name": opt(text()), "ssn": opt(text())})
    p.entity("members", key="member_id",
             doc="Created at the earliest DateEntered of their entertainers (a rule)",
             cols={"ext_id": text(), "first_name": opt(text()), "last_name": opt(text()),
                   "gender": opt(text())})
    p.entity("entertainer_members", key="em_id",
             doc="Created at the entertainer's DateEntered; the status is a snapshot",
             cols={"ext_id": text(doc="'<EntertainerID>/<MemberID>'"),
                   "entertainer_id": ref("entertainers"), "member_id": ref("members")})
    p.entity("musical_styles", key="style_id", doc="Created at T0 = 1995-01-20 (a rule)",
             cols={"ext_id": text(), "style_name": opt(text())})
    p.entity("entertainer_styles", key="es_id",
             doc="Created at the entertainer's DateEntered; the strength rank is a snapshot",
             cols={"ext_id": text(doc="'<EntertainerID>/<StyleID>'"),
                   "entertainer_id": ref("entertainers"), "style_id": ref("musical_styles")})
    p.entity("customers", key="customer_id",
             doc="Created at their first engagement's start; the 2 with none at T0 (rules)",
             cols={"ext_id": text(), "first_name": opt(text()), "last_name": opt(text())})
    p.entity("musical_preferences", key="mp_id",
             doc="Created with their customer; the preference rank is a snapshot",
             cols={"ext_id": text(doc="'<CustomerID>/<StyleID>'"),
                   "customer_id": ref("customers"), "style_id": ref("musical_styles")})
    p.event("engagement_booked",
            doc="At the performance start: the booking time is unknown (a rule)",
            cols={"customer_id": ref("customers"), "engagement_number": i64(),
                  "entertainer_id": ref("entertainers"), "agent_id": ref("agents"),
                  "end_date": text(doc="'YYYY-MM-DD'"),
                  "stop_time": text(doc="'HH:MM:SS'; at or after midnight in 17 rows"),
                  "contract_price": i64(doc="whole dollars")})
    p.event("agents_snapshot", doc="State at N: address, phone and pay",
            cols={"agent_id": ref("agents"), "street_address": opt(text()),
                  "city": opt(text()), "state": opt(text()), "zip": opt(text()),
                  "phone": opt(text()), "salary": opt(i64(doc="whole dollars")),
                  "commission_rate": opt(f64())})
    p.event("entertainers_snapshot", doc="State at N: address and contact details",
            cols={"entertainer_id": ref("entertainers"), "street_address": opt(text()),
                  "city": opt(text()), "state": opt(text()), "zip": opt(text()),
                  "phone": opt(text()), "web_page": opt(text()), "email": opt(text())})
    p.event("members_snapshot", doc="State at N: the phone",
            cols={"member_id": ref("members"), "phone": opt(text())})
    p.event("entertainer_members_snapshot", doc="State at N: the member's status in the act",
            cols={"em_id": ref("entertainer_members"), "status": opt(i64())})
    p.event("entertainer_styles_snapshot", doc="State at N: the style's strength rank",
            cols={"es_id": ref("entertainer_styles"), "style_strength": i64()})
    p.event("customers_snapshot", doc="State at N: address and phone",
            cols={"customer_id": ref("customers"), "street_address": opt(text()),
                  "city": opt(text()), "state": opt(text()), "zip": opt(text()),
                  "phone": opt(text())})
    p.event("musical_preferences_snapshot", doc="State at N: the preference rank",
            cols={"mp_id": ref("musical_preferences"), "preference_seq": i64()})
