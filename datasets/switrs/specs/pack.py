"""SWITRS: California Highway Patrol collision reports, with their parties, victims and the
dump each case came from. Stage 1, schema only: the events are ingested from the Spider2
tables (docs/research/spider2/traffic.md).

Spider2 sampled the 4 tables independently (~1% each), so 99% of parties and victims have no
collision. There are no entities: every event is owned by the case it names. `case_id` is a
REAL, above 2^53 for the 2001 date-coded ids, so it rides as f64 in every payload and is never
read back from the log's entity key. Every source column travels verbatim: text stays text
(dirty codes and the pandas '.0' included), REAL stays f64, INTEGER stays i64.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, f64, i64, opt, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def t():
    return opt(text())


def r():
    return opt(f64())


def n():
    return opt(i64())


COLLISION = {
    "jurisdiction": r(), "officer_id": t(), "reporting_district": t(), "chp_shift": t(),
    "population": t(), "county_city_location": n(), "county_location": t(),
    "special_condition": r(), "beat_type": t(), "chp_beat_type": t(),
    "city_division_lapd": t(), "chp_beat_class": t(), "beat_number": t(), "primary_road": t(),
    "secondary_road": t(), "distance": r(), "direction": t(), "intersection": r(),
    "weather_1": t(), "weather_2": t(), "state_highway_indicator": r(), "caltrans_county": t(),
    "caltrans_district": r(), "state_route": r(), "route_suffix": t(), "postmile_prefix": t(),
    "postmile": r(), "location_type": t(), "ramp_intersection": t(), "side_of_highway": t(),
    "tow_away": r(), "collision_severity": t(), "killed_victims": r(), "injured_victims": r(),
    "party_count": r(), "primary_collision_factor": t(), "pcf_violation_code": t(),
    "pcf_violation_category": t(), "pcf_violation": r(), "pcf_violation_subsection": t(),
    "hit_and_run": t(), "type_of_collision": t(), "motor_vehicle_involved_with": t(),
    "pedestrian_action": t(), "road_surface": t(), "road_condition_1": t(),
    "road_condition_2": t(), "lighting": t(), "control_device": t(), "chp_road_type": t(),
    "pedestrian_collision": n(), "bicycle_collision": n(), "motorcycle_collision": n(),
    "truck_collision": n(), "not_private_property": r(), "alcohol_involved": r(),
    "statewide_vehicle_type_at_fault": t(), "chp_vehicle_type_at_fault": t(),
    "severe_injury_count": n(), "other_visible_injury_count": n(),
    "complaint_of_pain_injury_count": n(), "pedestrian_killed_count": n(),
    "pedestrian_injured_count": n(), "bicyclist_killed_count": n(),
    "bicyclist_injured_count": n(), "motorcyclist_killed_count": n(),
    "motorcyclist_injured_count": r(), "primary_ramp": t(), "secondary_ramp": t(),
    "latitude": r(), "longitude": r(),
}

PARTY = {
    "id": n(), "party_number": n(), "party_type": t(), "at_fault": n(), "party_sex": t(),
    "party_age": r(), "party_sobriety": t(), "party_drug_physical": t(),
    "direction_of_travel": t(), "party_safety_equipment_1": t(),
    "party_safety_equipment_2": t(), "financial_responsibility": t(),
    "hazardous_materials": r(), "cellphone_in_use": r(), "cellphone_use_type": t(),
    "school_bus_related": r(), "oaf_violation_code": t(), "oaf_violation_category": t(),
    "oaf_violation_section": r(), "oaf_violation_suffix": t(),
    "other_associate_factor_1": t(), "other_associate_factor_2": t(),
    "party_number_killed": n(), "party_number_injured": n(),
    "movement_preceding_collision": t(), "vehicle_year": r(), "vehicle_make": t(),
    "statewide_vehicle_type": t(), "chp_vehicle_type_towing": t(),
    "chp_vehicle_type_towed": t(), "party_race": t(),
}

VICTIM = {
    "id": n(), "party_number": n(), "victim_role": t(), "victim_sex": t(), "victim_age": r(),
    "victim_degree_of_injury": t(), "victim_seating_position": t(),
    "victim_safety_equipment_1": t(), "victim_safety_equipment_2": t(), "victim_ejected": t(),
}


def define(p: Pack) -> None:
    case = {"case_id": f64(doc="SWITRS case id as the source's REAL; above 2^53 for the 2001 "
                               "date-coded ids; never rebuilt from the key text")}
    p.event("collision_occurred", doc="At collision_date + collision_time (00:00 when NULL)",
            cols={**case, **COLLISION,
                  "time_known": i64(doc="0 for the 804 NULL collision_time")})
    p.event("collision_processed", doc="At process_date 00:00", cols=case)
    p.event("party_recorded", doc="Time is a rule: the collision's, the 2001 id's, or N",
            cols={**case, **PARTY})
    p.event("victim_recorded", doc="Time is a rule: the collision's, the 2001 id's, or N",
            cols={**case, **VICTIM})
    p.event("case_indexed", doc="A case_ids row: which CHP dump held the case; time is a rule",
            cols={**case, "db_year": i64()})
