# California Traffic Collision (Spider 2.0-lite): reverse-engineered event log

Source: `data/spider2/California_Traffic_Collision.sqlite` (92 MB), all 4 tables (`collisions`, `case_ids`, `parties`, `victims`), opened read-only. `scripts/traffic/rq.py` copies the file into an in-memory SQLite, adds indexes on `case_id`/`id` to the copy only, and runs named blocks; the file itself is never written.

Every number below comes from one of these scripts in `scripts/traffic/`:
- a named query in `q*.sql` (run with `rq.py`);
- `p1_columns.py` (per-column profile), `p2_case_id.py` (case_id as a key), `p3_sampling_dists.py` (sampling and distributions), all run with `python3 -I`;
- `p4_roundtrip.py` (JSON and DuckDB round-trip probes; run with `uv run --frozen python`, because it needs DuckDB 1.5.6);
- `p0_origin.sh` (Kaggle and Spider2 metadata).

Raw outputs are `out_<script>.txt` next to each script. A reference such as `[q2:severity_rule]` means file `q2_collisions.sql`, block `-- name: severity_rule`. Gold files are in `scripts/traffic/gold/`.

## 0. What this catalog is

- **Dataset.** This is **SWITRS** (California Highway Patrol's Statewide Integrated Traffic Records System) as packaged by **Alex Gude** on Kaggle: "California Traffic Collision Data from SWITRS", built with his `SWITRS-to-SQLite` tool [p0]. The evidence:
  - the table set is exactly Gude's: `collisions`, `parties`, `victims`, plus `case_ids`, which his description calls "a table … I used to build the other tables. It tells you which of the … original datasets each row came from" [p0];
  - his description says he combined CHP dumps requested in 2016–2021. Here `case_ids.db_year` ∈ {2017, 2018, 2020, 2021} [p1];
  - the codes are his human-readable remaps (`making left turn`, `had not been drinking`), with raw SWITRS letters leaking through where his value map has no entry (`party_drug_physical = 'G'` ×16,684, `road_surface = 'H'` ×2) [p1, q3:dirty_codes_pv].
- **Spider's change: every table is an independent ~1% sample.** The four tables were sampled separately, not as one collision with its parties and victims [q1, p3]:
  - only **1,831 of 186,692 parties** (0.98%) and **929 of 96,393 victims** (0.96%) have their collision in `collisions`. Only **993 of 94,243** `case_ids` rows match a collision (1.05%);
  - those three overlaps each estimate the collision sampling fraction independently: 0.981%, 0.964% and 1.054%. They imply a full table of 8.9–9.8 M collisions [p3];
  - the victim → (case, party_number) overlap gives a party fraction of 1.04%, or about 18.0 M parties in full [p3];
  - if parties were sampled independently, 1,925 collisions would be expected to have at least one sampled party. 1,824 do [p3];
  - in the sample, 184,477 cases have exactly 1 party, against `party_count` = 2 for 64,165 collisions [q3:parties_per_case, q2:party_count_dist].
- **Precision loss on `case_id`.** Gude's `case_id` is text. Here it is REAL, so the 19-digit 2001 ids lost their last 3–4 digits (see §3.1).
- **Row counts** [q1:row_counts]: collisions 94,243, case_ids 94,243, parties 186,692, victims 96,393. Total 471,571.
- **Coverage.** Collisions run 2001-01-01..2021-05-30, and `process_date` runs 2001-04-12..2021-06-03 [q2:snapshot].
- **Licence.** Kaggle lists **CC0: Public Domain** [p0]. The underlying data is CHP public records.
- **Nature.** **Real, administrative** police-report data. Persons are not named; the only quasi-identifiers are `officer_id`, coordinates and ages. It is neither generated nor course data.

## 0.1 How Spider 2.0 uses it

| id | asks | tables | gold SQL? | gold | reproduced |
|---|---|---|---|---|---|
| local015 | motorcyclist fatality rate by helmet use (parties' safety equipment) | collisions ⋈ parties | no (3 CSVs) | `_c`: helmet_used 18 collisions / 3 killed / 16.67%; not used 1 / 0 / 0.00 | ✔ exactly [q4:local015_helmet] |
| local017 | the year whose top-2 PCF categories differ from every other year | collisions | **yes** | `_b`: 2001 (`_a`: 2021) | ✔ the gold SQL returns 2001 [q4:local017_gold_sql] |
| local018 | top 2021 PCF category: share in 2011 − share in 2021 | collisions | no (1 CSV) | −0.553654 | ✔ speeding 31.3315% − 31.8852% = −0.553654 [q4:local018_shares] |

Notes:
- **local015 is a sampling artefact.** Only 53 of the 2,796 motorcycle collisions have any sampled party [q4:local015_join_size], so the "rate" rests on 19 collisions. The log must keep `case_id` bit-exact, or this join changes.
- **local017.** Every year's top 2 is speeding + improper turning, except 2001, where it is speeding + automobile right of way [q4:local017_top2_per_year]. The `_a` answer of 2021 is an alternative the gold SQL does not produce.

## 1. Inventory, keys, joins

No PK or FK is declared.

| Table | Rows | Key (measured) | Kind |
|---|---:|---|---|
| collisions | 94,243 | `case_id` unique (94,243 distinct) [q1:collisions_case_id_unique] | activity: one row per collision, with date, time and process date |
| case_ids | 94,243 | none. `case_id` has 94,242 distinct values; 1 **exact duplicate row** (1942011008163035136, 2018) [q1:case_ids_dup] | provenance: which CHP dump held the case |
| parties | 186,692 | none. `id` has 185,858 distinct values (834 ids used twice, by different rows; 745 of those pairs have case_ids more than 1e6 apart) [q1:parties_id_dups, q3:parties_id_dup_case_gap]. (case_id, party_number) is unique except 1 pair (ids 16273820/16273821, case 9575011021164015610) [q3:parties_dup_case_party] | activity attribute: a party of a collision |
| victims | 96,393 | none. `id` has 95,894 distinct values (499 ids twice) [q1:victims_id_dups] | activity attribute: a person injured or present |

- **No table has duplicate full rows** except `case_ids` (1 pair) [q1:parties_full_dup_rows, q1:victims_full_dup_rows, q1:case_ids_exact_dup_rows].
- The duplicated `id`s are consistent with Gude's per-dump row ids colliding when dumps were merged (§0). This is an inference, not verified.

Joins, all on `case_id` (REAL = REAL):

| Join | Children matched |
|---|---|
| parties → collisions | 1,831 / 186,692 (0.98%) [q1:parties_case_in_collisions] |
| victims → collisions | 929 / 96,393 [q1:victims_case_in_collisions] |
| victims → parties (case_id, party_number) | 1,001 / 96,393 [q1:victims_case_in_parties] |
| case_ids ↔ collisions | 993 both ways [q1:case_ids_in_collisions] |
| collisions with ≥1 party / ≥1 victim | 1,824 / 918 of 94,243 [q1:collisions_with_parties] |

- Across the 4 tables, the union of distinct `case_id`s is **460,904**. Of these, 90,570 appear only in collisions, 90,431 only in case_ids, 179,853 only in parties and 91,507 only in victims [p2].
- **Orphans are the norm, not dirt.** A `ref` from a party or victim to a collision would fail for 99% of rows, so there can be no FK refs in the pack.
- Where they do match, the joins are consistent:
  - sampled parties per case ≤ `party_count` in 1,824 of 1,824 cases;
  - Σ `party_number_killed` ≤ `killed_victims` in 1,824 of 1,824;
  - victim `party_number` ≤ `party_count` in 928 of 929 [q2:matched_party_count_vs_parties, q3:matched_parties_killed_vs_collision, q3:matched_victims_party_number_le_party_count].
- **Row order is random** in every table: adjacent rowids go up and down about 50/50 by key and by date [q1:rowid_order, q1:collisions_date_order]. This is the sampler's shuffle, with no load order to preserve.
- **No copies or derived tables.** No table is a function of another; `case_ids` does not even cover `collisions`.
- **`case_ids.db_year` vs collision year** (matched rows) [q1:case_ids_db_year_vs_collision_year]:
  - 2001–2007 come from the 2018 dump;
  - 2008 comes from 2020;
  - 2009–2021 come from 2021.

  CHP purges old years from later dumps, so `db_year` is the latest dump that still held the case.

## 2. Event catalogue

Decision asked in the brief: should parties and victims be **events on the collision**, or part of **one `collision_reported` payload**?
- Measured, the payload option cannot be exact. It would carry only the 1,831 parties and 929 victims whose collision is in the catalog, and drop **184,861 parties (99.0%) and 95,464 victims (99.0%)** [q1].
- So parties, victims and case_ids rows are **their own events**, owned by the case they name. The owner is the `case_id` value as a text key, not a ref to an entity.
- No owner entity table exists. 460,904 case keys are referenced, but only 94,243 have a collision.

| # | Event | Owner (ord) | Time | Time is | Attributes | Source rows | Count |
|---|---|---|---|---|---|---|---:|
| E1 | `collision_occurred` | case_id | `collision_date` + `collision_time`; NULL time (804) → 00:00:00 with `time_known = false` | natural (804 times by rule) | case_id (f64), the other 71 columns (all but case_id and the 3 dates), time_known | collisions | 94,243 |
| E2 | `collision_processed` | case_id | `process_date` 00:00 | natural | case_id (f64) | collisions | 94,243 |
| E3 | `party_recorded` | case_id (ord = party_number) | tiered rule T(case_id), below | 1,831 natural, 10,198 from the id, **174,663 by rule** | all 32 columns verbatim | parties | 186,692 |
| E4 | `victim_recorded` | case_id (ord = party_number) | T(case_id) | 929 / 6,009 / **89,455** | all 11 columns verbatim | victims | 96,393 |
| E5 | `case_indexed` | case_id | T(case_id) | 993 / 5,173 / **88,077** | case_id (f64), db_year (i64) | case_ids (duplicate row → 2 events) | 94,243 |

**Total events: 565,814.** There are **no entities**.

**The time rule T(case_id)** for rows without their own time [q3:*_time_source, p2, p4 §5b]:
1. If the case is in `collisions`, use that collision's E1 time. The row then sorts after E1, by block position and ord.
2. Else, if the id is a 2001 **date-coded** id (≥ 1e17), use the time it encodes. These ids are jurisdiction + `YYMMDDHHMM` + a tail.
   - The decode matches the collision's jurisdiction and date in 5,231 of 5,231 collisions, and its HH:MM in 5,086 [p2].
   - YYMMDD is valid in all of them (10,300 parties, 6,061 victims, 5,237 case_ids). HHMM is invalid in 70, 4 and 41 rows (mostly `2500`, "time unknown"); those use 00:00 [p4 §5b].
3. Else, use the snapshot **N = 2021-06-03**, the last `process_date` [q2:snapshot].

Rule 3 is imposed. The 7–8-digit counter ids are not a usable clock: by case_id, adjacent collisions go back in date 42,259 times in 89,011 pairs, and the neighbour-interpolated date error is p50 9 d, p99 210 d, max 4,878 d [p2]. Interpolating them would be a model, not a rule.

What is **not** an entity, and why:
- **Cases.** There is no case table. Its only candidate, `case_ids`, has a duplicate row and covers 1% of collisions.
- **Lookup values** (jurisdiction, county, officer, beat, vehicle make) are codes with no source table. `county_city_location` determines `county_location` and `population` exactly (525 codes, 0 conflicts) [q2:county_city_to_county_fd, q2:county_city_to_population_fd]. That is a stage-2 fact, not a table.
- **Persons.** Parties and victims are per-collision records with no person identity, so no person is ever seen twice.
- **Snapshot columns:** none. No column changes after the report, except `db_year`, which is provenance and rides on E5.

## 3. Rebuild rules and blockers to an exact round trip

1. **`case_id` is a REAL above 2⁵³** [p2, p4]:
   - 26,829 of 471,571 cells exceed 2⁵³ (5,231 in collisions), so they are already rounded doubles;
   - 10,979 cells exceed the int64 maximum, so `i64` is impossible.
   - **It must travel as `f64`.** Every REAL cell of all 4 tables, 2,311,339 cells in all, survives Python's shortest-repr JSON → DuckDB `json_transform(…DOUBLE)` with **0 differences** [p4 §1].
   - **The owner key text is only a key, never the value.** `CAST(case_id AS TEXT)` has 15 significant digits, and 25 of its texts stand for two different values [p2].
   - `printf('%.0f', case_id)` is injective (460,904 texts for 460,904 values) under both SQLite 3.45.1 and 3.47.1. But only under 3.45.1 does it read back exactly: under 3.47.1 (uv's), 8,148 of 471,571 texts read back as a different double, in both Python and DuckDB [p2, p4 §2, §6, §7].
   - So build.sql must take `case_id` from the payload field, never `CAST(entity_key AS DOUBLE)`.
2. **Dates and times.**
   - `collision_date` and `process_date` are valid `YYYY-MM-DD` in 94,243 of 94,243 rows.
   - `collision_time` is `HH:MM:SS` with seconds always `00`. It is NULL in 804 rows, and a true `00:00:00` in 59, so a NULL needs the `time_known` flag to stay distinct [q2:date_time_formats].
   - Through `event_time` (UTC) and DuckDB `strftime`, date, time and process date rebuild 94,243 of 94,243 [p4 §3, §4].
3. **Derived columns, proven but carried verbatim.**
   - `injured_victims` = severe + other_visible + complaint_of_pain in 94,220 of 94,220 non-NULL rows (23 NULL) [q2:injured_sum_rule].
   - `collision_severity` is exactly the worst non-zero count: fatal ⇔ killed > 0, then severe, then other visible, then pain, else property damage only, with 0 exceptions. The 23 rows with NULL counts still have a severity [q2:severity_rule].
   - `killed_victims` ≥ Σ per-mode killed in 94,220 of 94,220 [q2:killed_vs_mode_counts].
   - The `not chp` block (chp_shift, beat_type, chp_beat_type, chp_beat_class) moves together in 94,217 rows; the 26 exceptions have `chp_beat_class` NULL [q2:not_chp_consistency].
   - The caltrans null pattern has 3 shapes [q2:caltrans_null_pattern].
   - Rebuilding these would save nothing and adds a NULL-flag case, so all of them ride on E1 as is. Stage 2 should *generate* them with these rules.
4. **No mixed columns.** Every cell's storage class matches its declared affinity: REAL columns hold only real/NULL, INTEGER only integer, TEXT only text/NULL [p1]. No `''` and no `'\N'` in any column [p1].
5. **Numbers stored as text keep their pandas `.0`.** Carry these as text, byte-exact:
   - collisions: `reporting_district` 177, `chp_road_type` 165 (`'0'` vs `'0.0'`, `'1'` vs `'1.0'`), `chp_vehicle_type_at_fault` 897, `beat_number` 558;
   - parties: `chp_vehicle_type_towing` 356, `chp_vehicle_type_towed` 503 (`'0'` 1,605 / `'00'` 89,309 / `'0.0'` 503) [q2:text_dot_zero, q2:chp_road_type_values, q3:towed_codes].
6. **Floats.**
   - `latitude`, `longitude` and `postmile` are true decimals (5, 5 and 3 places); `distance` has 83 non-integers [q2:latlon_decimals, q2:real_columns_non_integer].
   - All other REALs are integer-valued: counts, flags, codes, ages and years [q2, q3:party_real_non_integer].
   - Carry all of them as `f64`. Any of them could be `i64` and be cast back to DOUBLE, but `f64` is exact already [p4 §1].
7. **Duplicates.** The duplicate `case_ids` row becomes 2 E5 events. Tables compare as multisets, so this is exact. Duplicate `id`s in parties and victims are just attribute values.
8. **Rows without time.** 373,575 of the 565,814 events (E3 + E4 + E5 under rules 2 and 3) get their time from T: 21,380 from a decoded 2001 id and **352,195** (62.2%) at N [q3:*_time_source].

**Verdict: exact round trip, with caveats.**
- All 4 tables rebuild from E1–E5 payloads plus `event_time`.
- The caveats are the f64 case_id, which must come from the payload, and the SQLite-version-dependent owner text.
- 62% of events sit at the rule time N.

## 4. Measured quirks

- **Independent sampling (§0)** is the dominant quirk. Every cross-table statistic, such as parties per collision or victims per party, is distorted by a factor of about 100.
- **`case_id` precision collapse.** The duplicate `case_ids` row and the one duplicate (case_id, party_number) in parties are most likely two distinct 19-digit ids rounded to the same double. The parties pair has consecutive ids 16273820/16273821 [q1, q3:parties_dup_case_party].
- **Process lag** (process − collision, days) [q2:process_lag_days, q2:per_year]:
  - 0 negative; same day 121; p10 11, p50 137, p90 504, p99 703, max 962;
  - the mean by year rises from 106 d (2001) to 562 d (2012), then falls to 39–51 d (2016–2020). That is a CHP backlog regime change, not a law.
- **Coordinates** appear from 2006 onwards: 0 rows in 2001–2005, 20 in 2006, and 60–77% of rows in 2017–2021 [q2:latlon_presence_by_year].
- **Times are rounded by the officer.** 17.2% fall on :00 or :30, 28.5% on a quarter hour and 64.6% on a 5-minute mark [q2:minute_rounding]. The 2001 ids put HHMM = `2500` for an unknown time [p4 §5b].
- **Dirty codes:**
  - in collisions: `pcf_violation_code` ∈ {`'`, `A`, `D`} 7, `motor_vehicle_involved_with = '2'` 2, `road_surface = 'H'` 2 [q2:dirty_codes];
  - in parties: `party_sex = 'X'` 37, `cellphone_use_type = '4'` 20, `movement_preceding_collision = 'S'` 1, `vehicle_make = '20002'` 1;
  - in victims: `victim_sex` ∈ {`'2'`, `'4'`} 2, `victim_safety_equipment_2 = 'Z'` 1 [q3:dirty_codes_pv];
  - officer_id begins with `#`, `` ` ``, `;`, `[`, `+` or `-` in 13 rows, and primary_road begins with `'`, `(`, `.` or `]` in 6 [q2:odd_leading_chars];
  - there is no leading or trailing whitespace and no non-ASCII text in the roads or makes [q2:whitespace, q3:party_whitespace].
- **Outliers:**
  - `victim_age` 999 ×1, plus 8 ages over 100 (up to 120) [q3:victim_age_outliers];
  - `party_age` over 100 ×8, 0 ×28, and 136 drivers under 14 [q3:party_age_outliers];
  - `vehicle_year` 2918 and one other future year, and 36 before 1950 [q3:vehicle_year_outliers];
  - `party_number` 45, 54 and 92 [q3:party_number_dist];
  - `distance` up to 5,575,680 ft, with 33 rows over 10 miles [q2:dirty_codes].
- **Inconsistent flags:** `pedestrian_collision = 0` but `motor_vehicle_involved_with = 'pedestrian'` ×77, and the reverse ×171 [q2:flag_vs_involved_with].
- **Constant column:** `not_private_property` = 1.0 in all 94,243 rows. Note also `alcohol_involved` ∈ {1.0, NULL}, and `hazardous_materials` and `school_bus_related` ∈ {1.0, NULL} [p1].

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| arrivals | 12.64 collisions/day over 7,455 days, variance 18.15 (overdispersed), 1 zero-day [p3] |
| per year | 5,231–5,444 (2001–2005), falling to 3,787 (2013), 4,860 (2017), 3,733 (2020, COVID); 2021 is truncated at 05-30 [q2:per_year] |
| day of week | Sun 11,127 … Fri 15,559 (peak) [q2:weekday_hour] |
| hour | trough at 03–04 h (about 1.1k), peak at 17 h (7,315) with a 07–08 h morning bump [q2:hour] |
| month | flat, 7.4k–8.4k; October is highest [p3] |
| severity | PDO 60.67%, pain 23.94%, other injury 12.37%, severe 2.35%, fatal 0.67% [q2:severity_mix] |
| PCF category | speeding 28,773, improper turning 16,490, right of way 11,227, DUI 6,977, unsafe lane change 6,642 … (23 values + NULL) [q2:pcf_category_mix] |
| collision type | rear end 30,895, broadside 18,510, sideswipe 16,962, hit object 15,334 … [q2:type_of_collision_mix] |
| hit and run | not 75,820, misdemeanor 15,810 (93% PDO), felony 2,613 [q2:hit_and_run_x_severity] |
| parties per collision | from `party_count` (not from the sampled parties): 1: 17,768; 2: 64,165; 3: 9,676; 4: 2,031; 5+: 603 [q2:party_count_dist] |
| process lag | p50 137 d, p90 504 d, regime-dependent by year [q2:process_lag_quantiles] |
| party type | driver 167,908, parked vehicle 12,048, pedestrian 3,072, bicyclist 2,613 [q3:party_type_mix] |
| at fault | party 1: 84.3%, party 2: 7.9%, party 3: 5.7% [q3:at_fault_rate_by_party_number] |
| party age | p5 18, p50 36, p95 69 [p3] |
| victim age | p5 4, p50 27, p95 68 [p3] |
| victim injury | no injury 42,655, pain 33,400, other visible 12,932, … killed 743 [q3:victim_role_vs_degree] |
| vehicle year | p5 1988, p50 2002, p95 2016 [p3] |
| distance (ft) | p50 100, p75 490, p95 2,640 [p3] |

## 6. simkit mapping sketch

```python
CASE = {"case_id": f64(doc="SWITRS case id as a REAL; >2^53 for 2001 ids; never rebuilt from the key text")}
p.event("collision_occurred", cols={**CASE, "time_known": i64(doc="0 for the 804 NULL collision_time"),
        "jurisdiction": opt(f64()), "officer_id": opt(text()), "reporting_district": opt(text()),
        "chp_shift": text(), "population": opt(text()), "county_city_location": i64(),
        "county_location": text(), ...,                     # the 71 columns: TEXT→text/opt(text), REAL→f64/opt(f64), INTEGER→i64
        "latitude": opt(f64()), "longitude": opt(f64())})
p.event("collision_processed", cols={**CASE})
p.event("party_recorded", cols={"id": i64(), **CASE, "party_number": i64(), "party_type": opt(text()),
        "at_fault": i64(), "party_age": opt(f64()), ..., "party_race": opt(text())})
p.event("victim_recorded", cols={"id": i64(), **CASE, "party_number": i64(), "victim_role": opt(text()),
        ..., "victim_ejected": opt(text())})
p.event("case_indexed", cols={**CASE, "db_year": i64()})
```

Text columns stay `text`, not `cat`, because the dirty codes (§4) must survive byte-exact.

Ingest (SQLite):
- `collision_occurred owner=case_key`, where `case_key = printf('%.0f', case_id)`. Time is `collision_date || 'T' || coalesce(collision_time,'00:00:00')`. ORDER BY case_id.
- `collision_processed owner=case_key`, at `process_date || 'T00:00:00'`. ORDER BY case_id.
- `party_recorded owner=case_key ord=party_number`, at T(case_id) as a CASE expression: a LEFT JOIN to collisions; else the decode of `printf('%.0f', case_id)` for ids ≥ 1e17 (YYMMDD, with HHMM only when valid); else `'2021-06-03T00:00:00'`. ORDER BY case_id, party_number, id.
- `victim_recorded`: the same, ORDER BY case_id, party_number, id.
- `case_indexed`: the same T, ORDER BY case_id, db_year.
- The 2001 decode reads the *text*. Only YYMMDD and HHMM are used, and they sit in the leading 16 significant digits, so the SQLite version does not matter for them (5,231 of 5,231 date matches) [p2].

build.sql (DuckDB):
- `collisions` = E1 ⋈ E2 on `entity_key`, which is 1:1 because case_id is unique:
  - `collision_date = strftime(e1.event_time,'%Y-%m-%d')`;
  - `collision_time = CASE WHEN time_known=1 THEN strftime(e1.event_time,'%H:%M:%S') END`;
  - `process_date = strftime(e2.event_time,'%Y-%m-%d')`;
  - `case_id` comes from E1's payload;
  - all other columns pass through.
- `parties`, `victims` and `case_ids` are straight projections of E3, E4 and E5. Their times are discarded, since none of these tables has a time column.

Volume: 565,814 events, so no sample profile is needed. Stage-2 owners are the **collision** (E1 → E2 after a lag drawn per year regime) and its parties and victims, generated *jointly* from `party_count` and the injury counts. The sampled orphan structure is a property of this Spider extract, not of the process.

## 7. Open questions and risks

- **The SQLite version changes `printf('%.0f')`** (3.45.1 is exact; 3.47.1 rounds to about 17 digits). The key text stays injective in both, so the round trip is safe as long as build.sql never parses the key. But the log bytes, and so the lock file, depend on the SQLite version used for ingest. Pin it, or compute the key in Python (`str(int(v))`, exact) if the ingest tool allows.
- **62% imposed times.** 352,195 events sit at N, and 21,380 at a decoded 2001 id time. A stream consumer sees a burst of 352k events at 2021-06-03. Stage 2 must not fit E3–E5 arrival times. An alternative is to stamp rule-3 rows at the catalog start (2001-01-01); both are equally imposed, and N matches the "invented times are capped at N" convention.
- **The envelope `entity_type` for an owner that is not an entity.** Precedent exists (`flight_id`, `book_ref`, `order_id` owners), but confirm that the log writer accepts `entity_type = 'case'` with no `case` entity.
- **local017's two gold CSVs disagree** (2001 vs 2021). The saved query should be the gold SQL, which gives 2001.
- **Spider's sampler** is unverified. The overlaps fit independent ~1% Bernoulli or uniform samples per table (§0), but the 94,243 = 94,243 row count of collisions and case_ids suggests a fixed-n draw with the same n.
- **The duplicate `id`s** in parties and victims are probably per-dump row ids, which would make `id` meaningless as a key. Unverified without Gude's full DB.
- **The full SWITRS DB** (Kaggle, 9.9 GB, CC0) would allow a non-sampled dataset where parties and victims really hang off their collision. That is a different dataset from this Spider catalog.

---

**Summary**
- Exact round trip: **yes, with caveats**: `case_id` must ride as `f64` in every payload (0 of 2,311,339 REAL cells differ via JSON → DuckDB), never parsed from the owner key text.
- Dataset name: **`switrs`**.
- 5 event types (`collision_occurred`, `collision_processed`, `party_recorded`, `victim_recorded`, `case_indexed`; 565,814 events), 0 entities.
- **Partly imposed**: collisions are natural (2 timed events each), but the 4 tables are independent ~1% samples, so 99% of parties and victims have no collision and 352,195 events (62%) get the rule time N.
- Hardest blocker: `case_id` is a REAL above 2⁵³ (10,979 cells above int64), whose text form depends on the SQLite version; and parties/victims cannot be attached to collisions at all.
