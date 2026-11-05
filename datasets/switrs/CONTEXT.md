# switrs

## What this is

SWITRS, the California Highway Patrol's Statewide Integrated Traffic Records System: collision reports, the parties and victims of collisions, and the CHP dump each case came from.

Version `v1`, kind `spider2`. The input is one ordered event log of 565,814 events; the output is the 4 source tables, rebuilt exactly, and the answers to 3 saved Spider 2.0 questions.

## Raw data

`California_Traffic_Collision.sqlite` (all 4 tables: `collisions`, `case_ids`, `parties`, `victims`). Real administrative police-report data, from Alex Gude's Kaggle packaging "California Traffic Collision Data from SWITRS" (CC0: Public Domain). No person is named.

Spider2 sampled each table on its own, at about 1%. So only 1,831 of 186,692 parties and 929 of 96,393 victims have their collision in `collisions`, and only 993 of 94,243 `case_ids` rows match a collision. `case_id` is a REAL. The 2001 ids have 19 digits and sit above 2^53, so they are already rounded doubles, and 10,979 cells are above the int64 maximum.

Dates and times read as UTC. Collisions run 2001-01-01 to 2021-05-30; `process_date` ends 2021-06-03. Parties, victims and case_ids rows have no time of their own. Their time is a rule.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/traffic.md`](../../docs/research/spider2/traffic.md).

## How the log was made

Each collision is two events, `collision_occurred` at its date and time and `collision_processed` at its process date. Each party, victim and `case_ids` row is one event. Every event is owned by the case it names, and there are no entities: 460,904 distinct case ids appear across the 4 tables, but only 94,243 have a collision. The duplicate `case_ids` row becomes 2 events.

`case_id` rides as f64 in every payload, and `build.sql` reads it from there. The log's `entity_key` is the f64's shortest round-trip text (460,904 texts for 460,904 values). It is only a key, never parsed back. Every other column travels verbatim: text stays text, dirty codes and the pandas `'.0'` texts included; REAL stays f64 and INTEGER stays i64. `time_known` is 0 for the 804 collisions with a NULL `collision_time`.

`uv run dataset build switrs` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `collision_occurred` | business | 94,243 | `case_id`, `jurisdiction`, `officer_id`, `reporting_district`, `chp_shift`, `population`, `county_city_location`, `county_location`, `special_condition`, `beat_type`, `chp_beat_type`, `city_division_lapd`, `chp_beat_class`, `beat_number`, `primary_road`, `secondary_road`, `distance`, `direction`, `intersection`, `weather_1`, `weather_2`, `state_highway_indicator`, `caltrans_county`, `caltrans_district`, `state_route`, `route_suffix`, `postmile_prefix`, `postmile`, `location_type`, `ramp_intersection`, `side_of_highway`, `tow_away`, `collision_severity`, `killed_victims`, `injured_victims`, `party_count`, `primary_collision_factor`, `pcf_violation_code`, `pcf_violation_category`, `pcf_violation`, `pcf_violation_subsection`, `hit_and_run`, `type_of_collision`, `motor_vehicle_involved_with`, `pedestrian_action`, `road_surface`, `road_condition_1`, `road_condition_2`, `lighting`, `control_device`, `chp_road_type`, `pedestrian_collision`, `bicycle_collision`, `motorcycle_collision`, `truck_collision`, `not_private_property`, `alcohol_involved`, `statewide_vehicle_type_at_fault`, `chp_vehicle_type_at_fault`, `severe_injury_count`, `other_visible_injury_count`, `complaint_of_pain_injury_count`, `pedestrian_killed_count`, `pedestrian_injured_count`, `bicyclist_killed_count`, `bicyclist_injured_count`, `motorcyclist_killed_count`, `motorcyclist_injured_count`, `primary_ramp`, `secondary_ramp`, `latitude`, `longitude`, `time_known` |
| `collision_processed` | business | 94,243 | `case_id` |
| `party_recorded` | business | 186,692 | `case_id`, `id`, `party_number`, `party_type`, `at_fault`, `party_sex`, `party_age`, `party_sobriety`, `party_drug_physical`, `direction_of_travel`, `party_safety_equipment_1`, `party_safety_equipment_2`, `financial_responsibility`, `hazardous_materials`, `cellphone_in_use`, `cellphone_use_type`, `school_bus_related`, `oaf_violation_code`, `oaf_violation_category`, `oaf_violation_section`, `oaf_violation_suffix`, `other_associate_factor_1`, `other_associate_factor_2`, `party_number_killed`, `party_number_injured`, `movement_preceding_collision`, `vehicle_year`, `vehicle_make`, `statewide_vehicle_type`, `chp_vehicle_type_towing`, `chp_vehicle_type_towed`, `party_race` |
| `victim_recorded` | business | 96,393 | `case_id`, `id`, `party_number`, `victim_role`, `victim_sex`, `victim_age`, `victim_degree_of_injury`, `victim_seating_position`, `victim_safety_equipment_1`, `victim_safety_equipment_2`, `victim_ejected` |
| `case_indexed` | business | 94,243 | `case_id`, `db_year` |

## Times set by rule

- A collision with a NULL `collision_time` (804 rows) occurs at 00:00:00 on its date, with `time_known = 0`.
- A party, victim or `case_ids` row takes the first of these that applies:
  1. its collision's time, when the case is in `collisions` (1,831 parties, 929 victims, 993 case_ids);
  2. for a 2001 date-coded id (≥ 1e17: jurisdiction, then YYMMDDHHMM, then a 5-digit tail), the date and HH:MM it encodes, or 00:00 when HHMM is not a valid time, such as `2500` (10,198, 6,009 and 5,173 rows);
  3. N = 2021-06-03 00:00:00, the last `process_date` (174,663, 89,455 and 88,077 rows).
- Rule 3 is imposed: 352,195 events, 62% of the log, sit at N. Stage 2 must not fit the arrival times of these events.
- The 2001 decode is exact integer arithmetic on the double. SQLite's `printf('%.0f')` is not used, because SQLite 3.47 rounds it to about 16 digits. For 630 ids, the carry out of a `…99999` tail would change the minute.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `collisions` | 94,243 | 75 | none |
| `case_ids` | 94,243 | 2 | none |
| `parties` | 186,692 | 32 | none |
| `victims` | 96,393 | 11 | none |

`expected/queries/` holds the answers of the saved questions (`local015`, `local017`, `local018`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

local015 joins parties to collisions on `case_id`. Only 53 of the 2,796 motorcycle collisions have a sampled party, so the answer rests on 19 collisions, and it changes if a single bit of `case_id` changes.

Every float column is declared in `dataset.toml` `[results.exact]`, so it compares bit for bit instead of within the usual relative 1e-9: `case_id` is a float id above 2⁵³, where 1e-9 would hide a changed id.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build switrs             # → $NEORISK_DATA_ROOT/switrs/v1/ (default data/datasets/)
uv run dataset verify switrs            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`. It should generate a collision's parties and victims together, from `party_count` and the injury counts. Their missing link here comes from Spider2's sampling, not from the process.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly. It must take `case_id` from the payload as a double.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
