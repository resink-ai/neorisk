-- SWITRS: source tables → events (refdata ingest). Every event is owned by its case_id (f64).
-- Parties, victims and case_ids rows have no time. Their time T(case_id) is a rule:
--   1. the collision's time, when the case is in `collisions`;
--   2. else, for a 2001 date-coded id (>= 1e17: jurisdiction + YYMMDDHHMM + a 5-digit tail),
--      the encoded date and HH:MM (00:00 when HHMM is not a valid time, e.g. '2500');
--   3. else N = 2021-06-03 00:00:00, the last process_date.
-- The decode is exact integer arithmetic on the double: case_id = hi * 2^32 + lo (both exact),
-- and floor(case_id / 1e5) = hi * 42949 + (hi * 67296 + lo) / 100000, since 2^32 = 42949e5 +
-- 67296. Its last 10 digits are YYMMDDHHMM. printf('%.0f', case_id) is not used: SQLite 3.47
-- rounds it to about 16 digits, and the carry from a ...99999 tail changes the minute digit.

-- event: collision_occurred owner=case_id
SELECT collision_date || ' ' || coalesce(collision_time, '00:00:00') AS event_time,
       case_id, jurisdiction, officer_id, reporting_district, chp_shift, population,
       county_city_location, county_location, special_condition, beat_type, chp_beat_type,
       city_division_lapd, chp_beat_class, beat_number, primary_road, secondary_road, distance,
       direction, intersection, weather_1, weather_2, state_highway_indicator, caltrans_county,
       caltrans_district, state_route, route_suffix, postmile_prefix, postmile, location_type,
       ramp_intersection, side_of_highway, tow_away, collision_severity, killed_victims,
       injured_victims, party_count, primary_collision_factor, pcf_violation_code,
       pcf_violation_category, pcf_violation, pcf_violation_subsection, hit_and_run,
       type_of_collision, motor_vehicle_involved_with, pedestrian_action, road_surface,
       road_condition_1, road_condition_2, lighting, control_device, chp_road_type,
       pedestrian_collision, bicycle_collision, motorcycle_collision, truck_collision,
       not_private_property, alcohol_involved, statewide_vehicle_type_at_fault,
       chp_vehicle_type_at_fault, severe_injury_count, other_visible_injury_count,
       complaint_of_pain_injury_count, pedestrian_killed_count, pedestrian_injured_count,
       bicyclist_killed_count, bicyclist_injured_count, motorcyclist_killed_count,
       motorcyclist_injured_count, primary_ramp, secondary_ramp, latitude, longitude,
       collision_time IS NOT NULL AS time_known
FROM collisions ORDER BY case_id;

-- event: collision_processed owner=case_id
SELECT process_date || ' 00:00:00' AS event_time, case_id FROM collisions ORDER BY case_id;

-- event: party_recorded owner=case_id ord=party_number
SELECT CASE WHEN ct IS NOT NULL THEN ct
            WHEN case_id >= 1e17 THEN
                '20' || substr(ymd, 1, 2) || '-' || substr(ymd, 3, 2) || '-' || substr(ymd, 5, 2)
                || CASE WHEN substr(hm, 1, 2) < '24' AND substr(hm, 3, 2) < '60'
                        THEN ' ' || substr(hm, 1, 2) || ':' || substr(hm, 3, 2) || ':00'
                        ELSE ' 00:00:00' END
            ELSE '2021-06-03 00:00:00' END AS event_time,
       case_id, id, party_number, party_type, at_fault, party_sex, party_age, party_sobriety,
       party_drug_physical, direction_of_travel, party_safety_equipment_1,
       party_safety_equipment_2, financial_responsibility, hazardous_materials,
       cellphone_in_use, cellphone_use_type, school_bus_related, oaf_violation_code,
       oaf_violation_category, oaf_violation_section, oaf_violation_suffix,
       other_associate_factor_1, other_associate_factor_2, party_number_killed,
       party_number_injured, movement_preceding_collision, vehicle_year, vehicle_make,
       statewide_vehicle_type, chp_vehicle_type_towing, chp_vehicle_type_towed, party_race
FROM (SELECT *, substr(code, 1, 6) AS ymd, substr(code, 7, 4) AS hm
      FROM (SELECT *, printf('%010d', (hi * 42949 + (hi * 67296
                     + CAST(case_id - hi * 4294967296.0 AS INTEGER)) / 100000) % 10000000000)
                     AS code
            FROM (SELECT p.*, CAST(p.case_id / 4294967296.0 AS INTEGER) AS hi,
                         c.collision_date || ' ' || coalesce(c.collision_time, '00:00:00') AS ct
                  FROM parties p LEFT JOIN collisions c ON c.case_id = p.case_id)))
ORDER BY case_id, party_number, id;

-- event: victim_recorded owner=case_id ord=party_number
SELECT CASE WHEN ct IS NOT NULL THEN ct
            WHEN case_id >= 1e17 THEN
                '20' || substr(ymd, 1, 2) || '-' || substr(ymd, 3, 2) || '-' || substr(ymd, 5, 2)
                || CASE WHEN substr(hm, 1, 2) < '24' AND substr(hm, 3, 2) < '60'
                        THEN ' ' || substr(hm, 1, 2) || ':' || substr(hm, 3, 2) || ':00'
                        ELSE ' 00:00:00' END
            ELSE '2021-06-03 00:00:00' END AS event_time,
       case_id, id, party_number, victim_role, victim_sex, victim_age,
       victim_degree_of_injury, victim_seating_position, victim_safety_equipment_1,
       victim_safety_equipment_2, victim_ejected
FROM (SELECT *, substr(code, 1, 6) AS ymd, substr(code, 7, 4) AS hm
      FROM (SELECT *, printf('%010d', (hi * 42949 + (hi * 67296
                     + CAST(case_id - hi * 4294967296.0 AS INTEGER)) / 100000) % 10000000000)
                     AS code
            FROM (SELECT v.*, CAST(v.case_id / 4294967296.0 AS INTEGER) AS hi,
                         c.collision_date || ' ' || coalesce(c.collision_time, '00:00:00') AS ct
                  FROM victims v LEFT JOIN collisions c ON c.case_id = v.case_id)))
ORDER BY case_id, party_number, id;

-- event: case_indexed owner=case_id
SELECT CASE WHEN ct IS NOT NULL THEN ct
            WHEN case_id >= 1e17 THEN
                '20' || substr(ymd, 1, 2) || '-' || substr(ymd, 3, 2) || '-' || substr(ymd, 5, 2)
                || CASE WHEN substr(hm, 1, 2) < '24' AND substr(hm, 3, 2) < '60'
                        THEN ' ' || substr(hm, 1, 2) || ':' || substr(hm, 3, 2) || ':00'
                        ELSE ' 00:00:00' END
            ELSE '2021-06-03 00:00:00' END AS event_time,
       case_id, db_year
FROM (SELECT *, substr(code, 1, 6) AS ymd, substr(code, 7, 4) AS hm
      FROM (SELECT *, printf('%010d', (hi * 42949 + (hi * 67296
                     + CAST(case_id - hi * 4294967296.0 AS INTEGER)) / 100000) % 10000000000)
                     AS code
            FROM (SELECT x.*, CAST(x.case_id / 4294967296.0 AS INTEGER) AS hi,
                         c.collision_date || ' ' || coalesce(c.collision_time, '00:00:00') AS ct
                  FROM case_ids x LEFT JOIN collisions c ON c.case_id = x.case_id)))
ORDER BY case_id, db_year;
