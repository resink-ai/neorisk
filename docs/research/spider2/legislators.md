# US Congress legislators (Spider 2.0-lite, `city_legislation`): reverse-engineered event log

Source: `data/spider2/city_legislation.sqlite` (44 MB), opened read-only. The file holds four unrelated catalogs. This report covers three tables: `legislators`, `legislators_terms` and `legislation_date_dim`. The others are covered in `jobpostings.md`, `aliens.md` and `cities.md`.

`scripts/legislators/rq.py` copies the file into an in-memory SQLite and runs named blocks; the file itself is never written. Every number below comes from one of these scripts:
- a named query in `scripts/legislators/q*.sql`;
- `profile.py` (per-column storage classes, NULL / `''` / `'\N'` counts);
- `fetch_tanimura.sh` and `cmp_tanimura.py` (the upstream CSVs, compared cell by cell).

The raw outputs are in `scripts/legislators/out_*.txt`. A reference such as `[q4:end_regularity]` means file `q4_lifecycle.sql`, block `-- name: end_regularity`. Gold answer CSVs are in `scripts/legislators/gold/`.

## 0. What this catalog is

- **Dataset.** Members of the US Congress, 1789–2020, from the **`unitedstates/congress-legislators`** project (the YAML files `legislators-current` and `legislators-historical`, flattened). The columns keep that project's names flattened: `id_bioguide`, `id_govtrack`, `id_icpsr`, `id_fec_0..2`, `other_names_end`, `terms` → one row per term.
- **Exact lineage.** It is the Chapter 4 ("Cohorts") data of **Cathy Tanimura, *SQL for Data Analysis* (O'Reilly, 2021)**, repo `cathytanimura/sql_book`. The evidence:
  - `legislators.csv` (12,518 rows) and `legislators_terms.csv` (44,063 rows) equal the two tables **cell for cell, in row order**: 0 differing rows, identical headers [cmp_tanimura].
  - The repo's DDL comments map each column to the YAML path (`full_name varchar --name_official_full`, `url varchar --terms_1_url`) [fetch_tanimura].
  - The book's cohort queries join to a `date_dim` on `month_name = 'December' and day_of_month = 31`. `legislation_date_dim` is that dimension cut to three columns and to 1917–1999 (§1.1).
- **Loader fingerprint.** The CSV's integer columns that contain empties became `REAL` (`district`, `class`, `id_icpsr`, `id_house_history`, `id_thomas`, `id_cspan`, `id_votesmart`, `other_names_middle`), while `id_govtrack` (no empties) is `INTEGER` [profile]. That is pandas `to_sql`. No CSV cell in those columns has a decimal point [cmp_tanimura].
- **Snapshot.** The last term start is 2020-05-19 and the last past term end is 2020-05-22 (John Ratcliffe's resignation). 537 terms run past that, to scheduled ends 2020-11-03 … 2025-01-03 [q4:snapshot_N, q4:open_terms_end_dates]. So the YAML was exported in late May or June 2020. **N = 2020-05-22.**
- **Row counts** [profile]: legislators 12,518, legislators_terms 44,063, legislation_date_dim 30,315.
- **Licence.** `congress-legislators` is public domain (CC0). Tanimura's repo declares no licence [fetch_tanimura]. The date dimension is generated, so it carries none.
- **Nature.** Real, public historical records, not anonymised. The date dimension is generated.

## 0.1 How Spider 2.0 uses it

Four questions use these tables. None has gold SQL; each has two exec_result CSVs (`_a`, `_b`), and **all eight reproduce** [q2]. The `_a`/`_b` split is exactly "every December 31" against "December 31 rows of `legislation_date_dim`", so the calendar's 1917–1999 range changes three of the four answers.

| id | asks | gold SQL? | gold | reproduced |
|---|---|---|---|---|
| local169 | retention, years 1–20, of the cohort whose first term starts 1917–1999 (serving on Dec 31 of year k) | no (2 CSVs) | cohort 4,033; year 1 3,956 (98.09%) … year 20 707 (17.53%) | ✔ `_a` and `_b` (same numbers, as a fraction) exactly, using every Dec 31 [q2:local169_all_dec31]. Joining to the dim instead gives year 1 3,909 … year 20 514, which no CSV has [q2:local169_with_date_dim] |
| local167 | state (of first term) with most female legislators whose terms cover a Dec 31 | no (2 CSVs) | `_a` CA 42; `_b` CA 25 | ✔ `_a` with any Dec 31 [q2:local167]; ✔ `_b` with the dim's Dec 31s [q2:local167_with_date_dim] |
| local171 | male Louisiana legislators serving on Dec 31 of years 31–49 after their first term | no (2 CSVs) | 31: 6, 32–34: 5, 35: 4, 36: 2, 37–38: 1, then 0 (`_b` stops at 38) | ✔ both, when "Louisiana" is the state of the covering term [q2:local171_state_any_term]. State of the first term gives 5,4,4,4,3,1,1,1 [q2:local171] |
| local170 | states where both genders keep retention > 0 at years 0, 2, 4, 6, 8, 10 | no (2 CSVs) | `_a` 34 states (AK … WY); `_b` 23 states | ✔ `_a` with every Dec 31 [q2:local170]; ✔ `_b` with the dim [q2:local170_with_date_dim] |

All four need `term_start`, `term_end`, `state`, `gender` and the term order verbatim, and the calendar with its exact range.

## 1. Inventory, keys, joins

No PK or FK is declared. All keys below are verified unique [q1:key_uniqueness].

| Table | Rows | Key | Kind |
|---|---:|---|---|
| legislators | 12,518 | id_bioguide (also id_govtrack) | party / biography |
| legislators_terms | 44,063 | term_id = `id_bioguide || '-' || term_number` (44,063 of 44,063) [q1:term_id_rule] | activity: one row per term, with 2 dates |
| legislation_date_dim | 30,315 | date | **derived**: a generated calendar (§1.1) |

Joins and coverage:
- terms → legislators: 0 orphans; every legislator has at least one term [q1:fk_orphans].
- `term_number` is dense 0..n−1 for all 12,518 people [q1:term_number_dense], and it is exactly the rank of `term_start` within the person (44,063 of 44,063). Starts never go back or repeat, and no term overlaps the previous one; 7,882 terms start on the day the previous one ended [q1:term_number_in_start_order].
- `id_bioguide_previous_0` is set for 3 people (F000247, Y000061, G000408). Their previous ids (F000246, L000266, W000790) are not rows here [q1:fk_orphans, q4:previous_bioguide].
- Row order: legislators rowid 1..539 is the YAML "current" file and the rest is "historical". 537 of the 539 have a term open at N; the other 2 (William Floyd, John Reed, both 18th century) sit in the current block anyway [q4:current_block_is_open, q5:current_block_stragglers]. Terms rowid follows (term_number, legislator rowid) for 17,605 of 44,063 rows only [q4:terms_rowid_sort]. Results compare as multisets, so row order is not rebuilt.

### 1.1 `legislation_date_dim` is a generated calendar

- It holds every day from 1917-01-01 to 1999-12-31 exactly once: 30,315 rows = 30,315 days in the span [q3:span].
- A recursive CTE producing `(date, English month name, day number)` for that span equals the table **in both directions: 0 rows EXCEPT either way** [q3:generated_vs_source].
- rowid = day number since 1917-01-01 for all 30,315 rows [q3:rowid_is_date_order]. Types: date TEXT, month_name TEXT, day_of_month INTEGER [q3:types].
- It is a 3-column cut of Tanimura's `create_date_dimension.sql` (`generate_series('1770-01-01','2030-12-31')`, 22 columns, of which `date`, `month_name` and `day_of_month` survive) [fetch_tanimura].
- The range matches local169's cohort window, not the data: 18,052 terms end before 1917 and 4,859 start after 1999 [q3:range_vs_terms]. It has 83 Dec-31 rows [q3:used_by_questions_dec31].

**Verdict: derived, no events.** `build.sql` regenerates it from two constants.

## 2. Event catalogue

**Term lifecycle.**
- Both dates are `YYYY-MM-DD` and valid in every row; every term ends after it starts [q1:date_formats, q1:end_vs_start].
- `term_end` mixes two things. 43,360 term ends fall on a statutory boundary: Mar 3/4 before 1935, Jan 3 from 1935. The other 703 (244 rep, 459 sen) are early or irregular ends, such as deaths, resignations and special elections [q4:end_regularity]. So the end is an event, not a promise known at the start.
- 537 terms are still open at N, and their `term_end` is a scheduled future date: 2021-01-03 for 437 reps and 34 senators; 2023-01-03 for 32 senators; 2025-01-03 for 33; and 2020-11-03 for 1 (an appointee until the special election) [q4:open_terms_end_dates].

| # | Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `term_started` | legislator (ord = 2·term_number) | `term_start` (natural) | term_number, term_type (rep/sen), state, district (opt), class (opt), party (opt), how (opt), state_rank (opt), caucus (opt), url, address, phone, fax, contact_form, office, rss_url (all opt), **scheduled_end** (opt: set only on the 537 terms open at N) | legislators_terms | 44,063 |
| E2 | `term_ended` | legislator (ord = 2·term_number + 1) | `term_end` (natural) | term_number | terms with term_end ≤ N | 43,526 |

**Total events: 87,589** [q5:event_counts]. `term_id` is not carried: it is `id_bioguide || '-' || term_number` (§3).

Entities (1 table, 12,518 rows):
- **legislators**: ext_id = id_bioguide. `created_at` = the first `term_start` (rule: entering Congress), which runs 1789-03-04 .. 2020-05-19 [q5:entity_created_at]. It carries the biography: names, birthday, gender, id_bioguide_previous_0, other_names_*, id_govtrack, id_icpsr, id_house_history(_alternate), id_wikipedia, id_wikidata, id_google_entity_id.
- **Snapshot columns** go into one `legislators_snapshot` event at N per legislator (12,518). They are the modern cross-reference ids `id_fec_0..2`, `id_opensecrets`, `id_votesmart`, `id_cspan`, `id_ballotpedia`, `id_thomas` and `id_lis`. These were assigned by agencies long after most careers ended. The evidence: they are present only for people who served after 1970 (FEC 1,083, OpenSecrets 1,209, Thomas 2,181 of 2,509), and 0 of the 10,009 who left before 1971 have any of them [q5:snapshot_style_ids_by_era]. `full_name` is `name_official_full` as of 2020; it is classed as creation data, but the call is open (§7).

What is **not** an entity or an event, and why:
- **Terms are events, not entities.** A term is a start and an end of one person's service. There is no term-level lookup that other tables reference.
- **`legislation_date_dim`** is derived (§1.1). It is not a calendar entity, because it is a pure function of two constants.
- **Party changes, state changes and chamber switches** are attributes of E1. 1,003 continuing terms change party, 55 change state and 701 people serve in both chambers [q4:party_changes, q4:state_changes, q4:type_switch]. No separate event exists in the source.
- **Birthday** is an attribute. Using it as `created_at` would fail 551 rows (NULL) and would put creation before 1789 for many people.

## 3. Rebuild rules and blockers to an exact round trip

1. **term_end** = `coalesce(E2.event_time, E1.scheduled_end)`, formatted `%Y-%m-%d`: 44,063 of 44,063 [q5:term_end_roundtrip]. The alternative is to put `term_end` on E1 for every term, which is also exact but carries the 703 irregular ends from their future.
2. **Same-day handover.** 7,882 terms start on the previous term's end day [q5:same_day_end_then_start]. No later term starts before an earlier one ends (0) [q5:same_day_start_end_conflict]. With ord = 2·term_number for E1 and 2·term_number + 1 for E2, term k's end (2k+1) sorts before term k+1's start (2k+2) on the same day, so the log never shows two open terms. The tables rebuild identically either way, because the views join on term_number, not on seq.
3. **term_id** = `id_bioguide || '-' || term_number` (44,063 of 44,063) [q1:term_id_rule]. **term_number** is the 0-based rank of E1 within the owner (44,063 of 44,063) [q1:term_number_in_start_order]; carry it anyway, as it is cheap and avoids a window function.
4. **REAL columns are integers.** district, class, id_icpsr, id_house_history, id_thomas, id_cspan and id_votesmart have 0 non-integral values [q1:real_columns_integral]. They round-trip through `CAST(x AS INTEGER)` and back exactly: 40,190 of 40,190, 3,873 of 3,873, 12,298 of 12,298 and 11,026 of 11,026 [q5:real_cols_as_int_roundtrip, q5:real_cols_legislators]. `id_house_history` reaches 15,032,449,022, beyond int32, so use `i64`. Results type them float64 (REAL affinity) and compare by value, so `opt(i64)` in the log is exact. `other_names_middle` is REAL and 100% NULL [profile]: build it as `CAST(NULL AS REAL)`.
5. **district sentinels.** district = −1 on 1,366 rep terms and 0 on 915 (at-large) [q1:district_values]. District is NULL exactly on senate terms and class is NULL exactly on house terms [q1:type_columns]. Carry both as opt.
6. **NULL vs empty.** No `''` and no `'\N'` in any column [profile]. Three URLs end in a space (`http://kirk.senate.gov/ `, …) [q1:url_whitespace]: keep text byte-exact.
7. **Dates as text.** term_start, term_end, birthday and other_names_end are all valid `YYYY-MM-DD` [q1:date_formats]. Read them as UTC midnight and format them back. Times run back to 1721 (birthdays) and 1789 (terms); µs timestamps cover that, but check the Parquet writer and engines with pre-1900 dates.
8. **The calendar** is `WITH RECURSIVE g(d) AS (SELECT '1917-01-01' UNION ALL SELECT date(d,'+1 day') FROM g WHERE d < '1999-12-31')`, plus a month-name CASE and `CAST(strftime('%d', d) AS INTEGER)`: 0 differing rows [q3:generated_vs_source].
9. **Rows without time.** Only the entity's `created_at` is set by a rule (first term start), and every event time is a source date.

**Verdict:** exact. The only design choice is whether open terms' scheduled ends ride on E1 (`scheduled_end`) or every E1 carries `term_end`.

## 4. Measured quirks

- **Born after first term.** William Mayrant (M000288): born 1816-10-21, first term 1815-12-04 [q4:born_after_first_term]. 5 people are under 20 at their first term (3 in the 0–9 band) [q4:age_at_first_term]. These are source errors; keep them.
- **551 birthdays are NULL**, mostly 18th–19th-century members (92 of 365 first seated in the 1700s, 454 of 6,300 in the 1800s, 5 in the 1900s) [q4:null_birthday_by_era]. 452 terms have NULL party, falling to 0 after 2000 [q4:party_null_by_era].
- **Contact columns exist only from 1999.** url, address, phone, office and similar are non-NULL on 4,393 terms, the earliest starting 1999-01-06 [q1:contact_cols_only_recent]. They are not limited to the last term: only 890 of 2,492 `office` values and 1,188 of 4,386 `url` values are on the person's last term [q1:contact_cols_last_term_only, q1:url_rows_by_last].
- **Territories and odd states.** 59 state codes, including DK (Dakota Territory), OL (Orleans Territory), PI (Philippines), and delegates from AS, GU, MP, PR, VI and DC [q1:states].
- **Names.** 180 full names are shared by 388 people [q1:duplicate_full_names]. 5 people have `other_names_*` (maiden names, such as Mary Bono Mack ← Bono) [q4:other_names].
- **Rare values.** `how` = 'appointment' on 201 senate terms; `caucus` = 'Democrat' on 14 terms (independents); 38 parties appear on fewer than 10 terms [profile, q1:party_rare].
- **Row-order fingerprint.** 2 historical people sit in the "current" rowid block [q5:current_block_stragglers].
- **Generator fingerprint** only in the date dim (§1.1). The legislators data is real.

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| new legislators per decade | 89 (1780s) … 822 (1890s); 397–580 per decade 1940s–1990s; 446 in the 2010s [q4:first_starts_by_decade] |
| term starts | bunched on Congress opening days: up to 499 starts on one date (1929-04-15); 263 distinct rep start dates, 580 senate [q4:starts_per_date_top, q4:start_regularity] |
| term length | rep: 727–731 d (two years) or 451–457 d (old December-session starts) [q1:term_lengths_days]; senate: six years |
| terms per legislator | 1: 4,139; 2: 2,734; 3: 1,505; 4: 1,008; long tail to 30 [q4:terms_per_legislator] |
| gap to next term | 0 d (contiguous) 7,882; 1–7 d 8,642; 8–400 d 13,358; 1–10 y 1,333; 10 y+ 330 [q4:gaps_between_terms] |
| early or irregular end | 244 of 40,190 rep terms (0.6%), 459 of 3,873 senate terms (11.9%) [q4:end_regularity] |
| party mix | Democrat 20,468, Republican 18,892, Whig 1,207, Jackson 878, Federalist 821, NULL 452 [q1:party_top] |
| gender | F 366 (2.9%), M 12,152 [q1:gender]. Female first-seated: 1 in the 1910s, 72 in the 1990s, 105 in the 2010s [q4:female_share_by_first_decade] |
| chamber | first term rep 11,197, sen 1,321; 701 served in both [q4:type_switch] |
| age at first term | 40s 4,610, 30s 3,405, 50s 2,718, 60s 805 [q4:age_at_first_term] |

## 6. simkit mapping sketch

```python
p.entity("legislators", key="legislator_id", cols={
    "ext_id": text(),  # id_bioguide
    "full_name": text(), "first_name": text(), "last_name": text(), "middle_name": opt(text()),
    "nickname": opt(text()), "suffix": opt(text()), "other_names_end": opt(text()), "other_names_last": opt(text()),
    "birthday": opt(text()), "gender": cat("F", "M"), "id_bioguide_previous_0": opt(text()),
    "id_govtrack": i64(), "id_icpsr": opt(i64()), "id_house_history": opt(i64()), "id_house_history_alternate": opt(i64()),
    "id_wikipedia": opt(text()), "id_wikidata": opt(text()), "id_google_entity_id": opt(text())})
# snapshot columns (legislators_snapshot at N): id_thomas, id_cspan, id_votesmart (opt i64); id_lis, id_ballotpedia,
# id_opensecrets, id_fec_0, id_fec_1, id_fec_2 (opt text)
p.event("term_started", cols={"legislator_id": ref("legislators"), "term_number": i32(), "term_type": cat("rep", "sen"),
        "state": text(), "district": opt(i64()), "class": opt(i64()), "party": opt(text()), "how": opt(text()),
        "state_rank": opt(cat("junior", "senior")), "caucus": opt(text()), "url": opt(text()), "address": opt(text()),
        "phone": opt(text()), "fax": opt(text()), "contact_form": opt(text()), "office": opt(text()),
        "rss_url": opt(text()), "scheduled_end": opt(ts())})
p.event("term_ended", cols={"legislator_id": ref("legislators"), "term_number": i32()})
```

Ingest:
- `legislators` ORDER BY id_bioguide; `created_at` = `iso_time(min(term_start), '%Y-%m-%d')`.
- `term_started owner=legislator_id ord=2*term_number`, ORDER BY id_bioguide, term_number; `scheduled_end` = term_end when term_end > N.
- `term_ended owner=legislator_id ord=2*term_number+1`, ORDER BY id_bioguide, term_number, WHERE term_end ≤ N.

`build.sql`:
- `legislators_terms` = E1 LEFT JOIN E2 on (owner, term_number); term_id = ext_id || '-' || term_number; term_end = `strftime('%Y-%m-%d', coalesce(E2.event_time, E1.scheduled_end))`; district and class `CAST(… AS REAL)`.
- `legislators` = creation ⋈ snapshot; the REAL ids are `CAST(… AS REAL)`; `other_names_middle` = `CAST(NULL AS REAL)`.
- `legislation_date_dim` = the recursive CTE of §3.8.

Stage-2 owners: **legislator** (arrivals clustered on Congress opening days; re-election as a geometric number of consecutive terms; a small early-end hazard, higher for senators). The volume is about 100k events, so no sample profile is needed.

## 7. Open questions and risks

- **Snapshot-column call.** The modern ids are classed as snapshot columns on measured evidence (§2). `full_name` is the 2020 official name, so it is arguably snapshot too. Moving it would not change the round trip.
- **`term_end` design.** `scheduled_end` only on open terms is honest about time but asymmetric; `term_end` on every E1 is simpler but leaks 703 irregular ends. Decide once, for every Spider2 "spell" table.
- **Pre-1900 timestamps** (1721 birthdays as text; events from 1789). Confirm the Parquet writer, DuckDB and Spark replay round-trip them.
- **The `_a`/`_b` gold split** depends on whether a query uses the date dim (§0.1). Saved queries must name their variant.
- **Licence.** CC0 upstream; Tanimura's repo is unlicensed. The rows are public-domain facts, so the risk is low.

## Summary

- Exact round trip: **yes**. Terms rebuild from start and end events, and the calendar from a generator (0 differing rows).
- Proposed dataset name: **`legislators`**.
- Event types: **2** business events (`term_started`, `term_ended`) plus the `legislators_snapshot`; **1** entity (legislators); `legislation_date_dim` is derived.
- Event shape: **natural**. Terms are real dated spells; only `created_at` (first term) and the snapshot split are rules.
- Hardest blocker: none hard. The design call is how open terms' future `term_end` is carried without leaking 703 irregular ends.
