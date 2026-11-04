# World cities (Spider 2.0-lite, `city_legislation`): reverse-engineered event log

Source: `data/spider2/city_legislation.sqlite` (44 MB), opened read-only. The file holds four unrelated catalogs. This report covers four tables: `cities`, `cities_countries`, `cities_currencies` and `cities_languages`. The others are covered in `legislators.md`, `jobpostings.md` and `aliens.md`.

`scripts/cities/rq.py` copies the file into an in-memory SQLite and runs named blocks (`setup*` blocks index the in-memory copy); the file itself is never written. Every number below comes from one of these scripts:
- a named query in `scripts/cities/q*.sql`;
- `profile.py` (per-column storage classes, NULL / `''` / `'\N'` counts);
- `fetch_shaker.sh` and `cmp_shaker.py` (the upstream raw CSVs, replayed through the upstream cleaning SQL).

The raw outputs are in `scripts/cities/out_*.txt`. A reference such as `[q1:lat_long_swapped]` means file `q1_keys.sql`, block `-- name: lat_long_swapped`. Gold answer CSVs are in `scripts/cities/gold/`.

## 0. What this catalog is

- **Dataset.** It is **Jaime M. Shaker's "SQL Coding Challenge"** (`github.com/iweld/SQL_Coding_Challenge`, Aug 2023): a world-cities table with deliberately dirtied text, a synthetic `insert_date`, and country, currency and language lookups. The tables here are his `cleaned_data` schema, after `normalize_tables.sql` and `remove_duplicates.sql`, with a `cities_` prefix.
- **Exact lineage, proven by replay.** `cmp_shaker.py` applies his cleaning to his raw CSVs: `trim(lower(regexp_replace(x, '[^\w\s^. ]', '')))`, `capital::boolean`, `population::int`, the dedup on `country_code_2` keeping the lowest id, and his latitude/longitude swap. The result equals the Spider tables cell for cell:
  - countries: 257 raw rows; the dedup drops 16 ids; 241 rows remain, 0 differ;
  - cities: 44,622 rows, 1 differing cell (city 9272, see below);
  - currencies: 254 rows, 0 differ; languages: 608 rows, 0 differ [cmp_shaker].
- **Loader fingerprint.** City 9272's raw name is `nan` (a town in Thailand). It is NULL here [cmp_shaker, q1:city_name_null]: pandas read the string "nan" as NaN when Spider loaded the cleaned table. `population` is REAL because it is an int column with NULLs [profile].
- **Origin of the rows.** The city rows look like simplemaps' World Cities "basic" file: ascii names, the largest cities first, Tokyo 37,732,000 first. The countries look like the ISO-3166 list with UN M49 regions. Both are unverified, since neither upstream was fetched (§7).
- **insert_date is synthetic.** Shaker's raw `insert_date` spans 2021-01-01..2023-08-01, every one of the 943 days, uniformly (§4) [cmp_shaker, q1:insert_date_format]. `created_on` = 2024-07-18 on all 241 countries is `current_date` when the normalize script was run, so the tables were built on 2024-07-18 [q1:created_on].
- **Row counts** [profile]: cities 44,622, cities_countries 241, cities_currencies 254, cities_languages 608.
- **Licence.** Shaker's repo declares none [fetch_shaker]. simplemaps' basic file is believed to be CC BY 4.0 (unverified).
- **Nature.** Course data. The city facts are real, the text is dirtied then cleaned, and the insert dates are generated.

## 0.1 How Spider 2.0 uses it

Four questions use these tables. None has gold SQL; each has `_a` and `_b` CSVs. All four reproduce [q2].

| id | asks | gold SQL? | gold | reproduced |
|---|---|---|---|---|
| local068 | cities inserted in Apr/May/Jun of 2021–2023; per-month running total across years; YoY growth of both, shown for 2022–2023 | no (2 CSVs) | 2022-04: 1,437 / 2,945 / −4.708223% / 95.291777% … 2023-06: 1,432 / 4,238 / 1.488306% / 51.0335% | ✔ exactly, all 6 rows [q2:local068] |
| local070 | Chinese cities, July 2021: the dates of the shortest and longest insert-date streaks, one city per date | no (2 CSVs) | streaks 07-12..07-13 (2 days) and 07-19..07-31 (13 days) | ✔ streaks [q2:local070_streaks]. `_a`'s city per date is the **lowest city_id** on all 15 dates [q2:local070_pick_min_id]. `_b` picks other cities on 6 dates, not by id order: an arbitrary pick among 2–5 candidates [q2:local070_cities_per_day] |
| local071 | June 2022: countries with the longest streak of consecutive insert days | no (2 CSVs) | br, in, us (`_b` uppercase) | ✔, each with 30 days [q2:local071] |
| local072 | the country with 9 distinct insert days in Jan 2022; its longest streak; the capital share within it | no (2 CSVs) | ir, 2022-01-20..22, 3 days, 5 rows, 1 capital, 20% | ✔ exactly [q2:local072]; ir is the only 9-day country [q2:local072_candidates] |

Every question is about `insert_date` streaks, so the synthetic dates are the catalog's event stream. local070 `_a` also depends on `city_id` order being kept.

## 1. Inventory, keys, joins

No PK or FK is declared. All keys below are verified unique, and rowid = id in cities, currencies and languages [q1:key_uniqueness, q1:rowid_is_id].

| Table | Rows | Key | Kind |
|---|---:|---|---|
| cities | 44,622 | city_id 1..44,622 | entity, with a time column (`insert_date`) |
| cities_countries | 241 | country_id (1..256, 15 gaps from the dedup); country_code_2, country_code_3 and country_name are all unique | lookup |
| cities_currencies | 254 | currency_id 1..254; (country_code_2, currency_code) is not unique (253 distinct) | lookup, country 1:N |
| cities_languages | 608 | language_id 1..608; (language, country_code_2) is not unique (602 distinct) | lookup, country 1:N |

Joins and coverage [q1:fk_coverage, q1:fk_orphans_list]:
- cities, currencies and languages → countries via `country_code_2`: 100% each, 0 orphans.
- 5 countries have no city [q1:countries_without_cities].
- Currencies per country: 1 for 215, 2 for 15, 3 for 3 [q1:currencies_per_country]. Languages per country: 1–22 [q1:languages_per_country].

No table is a copy of or derived from another table in this file. The whole catalog is, however, a function of Shaker's raw CSVs (§0).

## 2. Event catalogue

The source has one time column that means "happened": `cities.insert_date`. Every Spider question counts it as the moment a city was inserted.

| # | Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `city_inserted`, the creation event of the `cities` entity | country (ref `country_code_2`, 100% resolve); ord = city_id | `insert_date`: a natural column, but its values are generated | city_id (ext_id), city_name (opt), latitude, longitude, capital, population (opt) | cities | 44,622 |

**Total events: 44,622 creation events, and no other business events.**

Entities (4 tables, 45,725 rows):

| Entity | ext_id | created_at | Rows |
|---|---|---|---:|
| `countries` | country_code_2 (country_id carried as an attribute, because of its gaps) | the catalog start 2021-01-01 (rule), so every city's ref resolves to an existing country | 241 |
| `currencies` | currency_id | the catalog start (rule); ref country | 254 |
| `languages` | language_id | the catalog start (rule); ref country | 608 |
| `cities` | city_id | `insert_date` (E1) | 44,622 |

Snapshot columns: `cities_countries.created_on` (2024-07-18) is a load stamp, later than every city insert (the last is 2023-08-01). It goes into one `countries_snapshot` event at **N = 2024-07-18**. Using it as `created_at` would create every country 11 months after its last city.

What is **not** an event, and why:
- **There are no updates.** Population, capital and coordinates have one value each; no history exists.
- **Currencies and languages** are static reference data with no time.
- **Duplicate city names** are not duplicate events. 1,455 (name, country) groups cover 3,623 rows, but only 1 group shares coordinates too, and no two rows are identical apart from their id [q1:duplicate_cities, q1:same_place_twice, q1:exact_duplicate_rows_ignoring_id]. They are distinct towns, such as several `san jose` in one country.

## 3. Rebuild rules and blockers to an exact round trip

1. **Latitude and longitude are swapped** in the source: `latitude` holds longitudes (9,774 values with |x| > 90) and `longitude` holds latitudes (range −54.93..81.72) [q1:lat_long_swapped, q1:tokyo]. Shaker's normalize script inserts `i.longitude::float` into `latitude` [fetch_shaker]. The round trip must keep the **columns as stored**. Do not "fix" them in the log, or every distance query changes. Carry both as `f64` verbatim; they have 1–4 decimals [q3:coord_decimals].
2. **population** is REAL, holding integers only (0 non-integral), with 305 NULLs and 4 zeros [q1:population_zero_null]. Carry it as `opt(i64)` and `CAST(… AS REAL)` it in the view.
3. **capital** is INTEGER 0/1, from raw TRUE/FALSE (246 TRUE) [cmp_shaker].
4. **Text.** Everything is already lower-cased and stripped of punctuation other than `.`: 0 non-ASCII names, 0 hyphens, 0 apostrophes, 67 names with a dot [q1:name_chars]. Keep it byte-exact. The NULLs are city 9272's name, Antarctica's `sub_region` and `intermediate_region` (and 134 more intermediate regions), and South Georgia's currency_code [q1:city_name_null, q1:null_sub_region, q1:null_currency_code]. There are no `''` and no `'\N'` [profile].
5. **Dates.** insert_date is `YYYY-MM-DD` in all rows [q1:insert_date_format], and so is created_on. Read them as UTC midnight and format them back with `%Y-%m-%d`.
6. **Same-day ties.** 47.3 cities per day on average; up to 15 from one country on one day [q3:same_day_same_country, q3:insert_day_count_moments]. Within a day, `ord = city_id` keeps the source order. Multiset comparison doesn't need it, but local070 `_a` (lowest city_id per date) does, so city_id must be carried.
7. **Rows without time.** Countries, currencies and languages get the rule time 2021-01-01, and created_on rides on the snapshot.

**Verdict:** exact. Every column passes through; the only decisions are the snapshot treatment of `created_on` and not repairing the coordinate swap.

## 4. Measured quirks

- **The coordinate swap** (§3.1).
- **Generator fingerprint in insert_date.** Every one of the 943 days in 2021-01-01..2023-08-01 has inserts, 27–73 per day, with mean 47.32 and variance 51.0. That is Poisson, as from uniform iid date draws [q1:insert_per_day_dist, q3:insert_day_count_moments]. Months hold 1,281–1,532 each, except the truncated 2023-08 with 51 [q1:insert_per_month]. Weekdays are flat, 6,219–6,461 [q1:insert_weekday]. The dates are independent of population (mean day 468.8–474.0 across population bands) and of capital status (469.0 vs 469.7) [q1:insert_vs_population_independence, q1:capital_insert].
- **Population order is loose.** The file starts with the largest cities (Tokyo, Jakarta, Delhi), but it is not sorted. 142 of the first 896 adjacent pairs already increase, and 20,673 of 44,316 do overall. The first NULL population is at id 898 [q1:population_order_head, q1:population_rank_order].
- **Capitals.** 223 countries have 1 capital city, 10 have 2, 1 has 3, and 2 have none [q1:capitals_per_country].
- **Dedup gaps.** country_id has 15 gaps up to 256, because remove_duplicates.sql deleted 16 raw rows (one of them id 257) [q1:country_id_gaps, cmp_shaker].
- **The pandas `nan` → NULL** city name (§0).
- **Typo kept from upstream:** region `antartica` [q1:region_mix].

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| arrivals | Poisson ≈ 47.3 per day, flat over 943 days, with no weekday or seasonal effect [q3:insert_day_count_moments, q1:insert_weekday] |
| country of a city | in 5,933, us 5,393, br 2,903, de 1,733, ph 1,578, cn 1,562 …; 37 countries have 1 city and 11 have 1,000+ [q3:cities_per_country_top, q3:cities_per_country_bands] |
| population | p5 8,810, p25 12,186, p50 20,990, p75 47,971, p95 300,516, max 37,732,000; NULL 0.7% [q3:population_quantiles] |
| capital | 246 of 44,622 (0.55%) |
| per country-day | 1 city on 16,799 country-days, 2 on 4,111 … 15 on 1 [q3:same_day_same_country] |
| lookups | currencies 1–3 per country; languages 1–22 per country; regions africa 59, americas 57, asia 50, europe 48, oceania 26 [q1:region_mix] |

A stage-2 generator is: draw a city from the reference list, and draw `insert_date` uniformly on the window. The arrival process carries no signal beyond the rate.

## 6. simkit mapping sketch

```python
p.entity("countries", key="country_key", cols={"ext_id": text(), "country_id": i64(), "country_name": text(),
         "country_code_3": text(), "region": text(), "sub_region": opt(text()), "intermediate_region": opt(text()),
         "created_on": text()})                                              # created_on: snapshot column
p.entity("currencies", key="currency_key", cols={"ext_id": i64(), "country": ref("countries"),
         "currency_name": text(), "currency_code": opt(text())})
p.entity("languages", key="language_key", cols={"ext_id": i64(), "language": text(), "country": ref("countries")})
p.entity("cities", key="city_key", cols={"ext_id": i64(), "city_name": opt(text()), "latitude": f64(), "longitude": f64(),
         "country": ref("countries"), "capital": i32(), "population": opt(i64())})   # created_at = insert_date, event name city_inserted
```

Ingest:
- `countries` ORDER BY country_code_2, created_at 2021-01-01; `currencies` and `languages` ORDER BY id, created_at 2021-01-01.
- `cities` ORDER BY insert_date, city_id; created_at = `iso_time(insert_date, '%Y-%m-%d')`; owner = country; ord = city_id.

`build.sql`:
- `cities` = entity projection, `insert_date = strftime('%Y-%m-%d', created_at)`, `population = CAST(population AS REAL)`;
- `cities_countries` = creation ⋈ snapshot (created_on);
- `cities_currencies` and `cities_languages` = projections, with `country_code_2` from the ref's ext_id.

Stage-2 owners: one **country** shard per country, inserting cities at a country-weighted Poisson rate. The volume is about 46k events, so no sample profile is needed.

## 7. Open questions and risks

- **Upstreams not fetched.** That the city rows are simplemaps World Cities basic, and the countries the ISO-3166/M49 list, is inferred from values, not compared. Shaker's CSVs are proven to be the direct source [cmp_shaker].
- **Licence.** Shaker's repo is unlicensed. simplemaps basic requires attribution (CC BY 4.0, unverified). Fitting statistics is fine; check before redistributing rows.
- **Entity vs event naming.** Cities are both a lookup and the only event stream. Modelling them as an entity whose creation event is `city_inserted` follows the contract. A separate business event would duplicate it.
- **created_on as snapshot** (2024-07-18, after every insert) versus as `created_at`: the snapshot is honest about time. Both round-trip.
- **local070 `_b`** picks cities arbitrarily, so no deterministic engine reproduces it. Saved queries should use `_a`'s lowest-id rule.

## Summary

- Exact round trip: **yes**. All four tables pass through verbatim, including the swapped coordinates and pandas' `nan` → NULL.
- Proposed dataset name: **`cities`**.
- Event types: **1** (`city_inserted`, the cities creation event, plus `countries_snapshot`); **4** entities (countries, currencies, languages, cities).
- Event shape: **partly imposed**. One natural time column, but its values are generated uniform dates; the lookups get rule times.
- Hardest blocker: none technical. Keep the source's latitude/longitude swap and city_id order as-is (local070 `_a` needs them); treat `created_on` as a snapshot, because it postdates every event.
