# refdata

Reference datasets: real tables from the [Spider 2.0](https://github.com/xlang-ai/Spider2) text-to-SQL benchmark, turned into simkit event logs and rebuilt exactly. Each one is a dataset in `datasets/` whose `pack.py` declares the events. Stage 1, this app, proves that the event log *is* the tables. Stage 2 will make the same pack generate the log, and grade it with the same views. See `docs/superpowers/specs/2026-10-30-spider2-reference-datasets-design.md`.

```bash
uv run refdata fetch                                   # 30 SQLite files → data/spider2/ (436 MB zip, sha256-pinned)
uv run refdata roundtrip datasets/olist [--force]      # ingest → log → rebuild → compare; exit 1 on any difference
uv run refdata ingest datasets/olist [--db SRC] [--out DIR] [--force]          # → data/ref/olist/
uv run refdata rebuild data/ref/olist.log --project datasets/olist [--out FILE] # log → data/ref/olist.rebuilt.sqlite
uv run refdata compare data/spider2/E_commerce.sqlite data/ref/olist.rebuilt.sqlite --project datasets/olist
uv run datagen check data/ref/olist --project datasets/olist --skip-stats        # structural checks on real data
```

Exit codes are 0 for success, 1 when a round trip or comparison differs, and 2 for a usage error, a missing source or a refusal.

Everything under `data/` is git-ignored. The sources' licences vary (Olist is CC BY-NC-SA 4.0), so only specs, SQL and research are committed.

## A project's files

| File | Holds |
|---|---|
| `specs/pack.py` | The entities and events (stage 1 declares only these) |
| `specs/source.toml` | The source file, and each source table's key (used only to sort diff samples) |
| `specs/ingest.sql` | SQLite SQL, with one `-- event: <name> owner=<col> [ord=<col>]` or `-- entity: <name> [event=<event_name>]` block per pack table. `event=` gives the creation event a domain name such as `customer_signed_up`, in place of `<entity>_created`; the log view keeps the entity's name |
| `specs/build.sql` | DuckDB SQL, with one `-- table: <name>` block per source table, read over the event log (decoded into one view per event type and entity by `refdata.logviews`) |
| `specs/queries/<id>.sql` | Spider2 questions, run on the source and on the rebuilt file |

## Dataset conventions

An ingested dataset has simkit's layout, so `neorisk_simkit.io.read`, `datagen check`, `datagen schema --load` and `datagen replay` all work on it.

- **Time:** source wall clock is stored as if it were UTC. Ingest SQL emits ISO text and may call `iso_time(text, strptime_format)`. Views format times back into the source's exact text.
- **Entities:** an entity's key is the 1-based rank of its `ext_id`, the source id held verbatim. `created_at` comes from the block if given, otherwise it is the first event time.
- **Refs:** a `ref(T)` column, in an event or an entity, is given as the source id and mapped through `T.ext_id`. An unmatched id is an error.
- **Order:** events sort by (event_time, `ord`, block position, owner, block row).
  - `seq = event_id` is that position.
  - `partition_id` ranks (owner column, owner value).
  - Every block ends in an ORDER BY.
- **Values:** money that is exact cents becomes `amount()` in minor units. Other floats are `f64`, and text is byte-exact.

## Exactness

A round trip passes when every source table equals the rebuilt one as a **multiset of rows**. INTEGER and REAL compare by value; NULL, `''` and `'\N'` are three different values. No tolerance applies to tables. Saved queries run on in-memory copies of both files, indexed on the `source.toml` keys. They compare as lists when the query has a top-level ORDER BY, otherwise as multisets, and float cells use a relative tolerance of 1e-9.

## The datasets

Measured on an Apple-silicon laptop: batch 1 on 2026-10-30, batch 2 on 2026-10-31, batch 3 on 2026-11-04. Batch 3 (from `ipl` on) is built with `dataset build`, not `roundtrip`, so it has no `roundtrip` time; its Events are the log's rows.

| Project | Source | Tables | Rows | Events | Queries | `roundtrip` |
|---|---|---:|---:|---:|---:|---:|
| `databank` | bank_sales_trading (Data Bank) | 3 | 9,373 | 9,368 | 6 | 1 s |
| `cliquebait` | bank_sales_trading (Clique Bait) | 5 | 34,537 | 32,734 | 1 | 2 s |
| `olist` | E_commerce | 11 | 1,559,764 | 918,549 | 12 | 41 s |
| `delivery_center` | delivery_center | 7 | 1,154,523 | 3,944,085 | 3 | 36 s |
| `airlines` | Airlines | 8 | 2,289,506 | 2,339,321 | 2 | 22 s |
| `sakila` | sqlite-sakila (= Pagila) | 16 | 46,273 | 47,954 | 9 | 3 s |
| `bitcoin` | bank_sales_trading (`bitcoin_*`) | 3 | 26,336 | 26,322 | 2 | 21 s |
| `weblog` | log | 19 | 854 | 834 | 5 | < 1 s |
| `pizzarunner` | modern_data (`pizza_*`) | 10 | 78 | 32 | 3 | 1 s |
| `chinook` | chinook | 11 | 15,607 | 2,652 | 3 | < 1 s |
| `northwind` | northwind | 15 | 3,366 | 3,794 | 2 | 1 s |
| `oraclesh` | complex_oracle | 10 | 1,064,608 | 1,000,955 | 6 | 19 s |
| `adventureworks` | AdventureWorks | 13 | 168,686 | 197,946 | 1 | 3 s |
| `ipl` | IPL | 8 | 293,471 | 150,518 | 11 | — |
| `f1` | f1 | 29 | 1,941,243 | 686,185 | 9 | — |
| `veg` | bank_sales_trading (`veg_*`) | 4 | 934,987 | 934,742 | 2 | — |
| `datamart` | bank_sales_trading (`weekly_sales`) | 2 | 34,234 | 17,117 | 2 | — |
| `freshsegments` | bank_sales_trading (`interest_*`) | 2 | 15,482 | 16,191 | 2 | — |
| `switrs` | California_Traffic_Collision | 4 | 471,571 | 565,814 | 3 | — |
| `eusoccer` | EU_soccer | 7 | 222,796 | 233,856 | 5 | — |
| `wwe` | WWE | 9 | 578,890 | 128,303 | 1 | — |
| `dbimdb` | Db-IMDB | 13 | 154,676 | 140,056 | 5 | — |
| `imdb_movies` | imdb_movies | 7 | 75,898 | 90,680 | 2 | — |
| `baseball` | Baseball | 26 | 553,693 | 572,700 | 2 | — |
| `atliq` | education_business (`hardware_*`) | 6 | 973,813 | 973,234 | 2 | — |
| `parchposey` | education_business (`web_*`) | 5 | 16,390 | 16,390 | 1 | — |
| `university` | education_business (`university_*`) | 5 | 76 | 132 | 1 | — |
| `staffhours` | education_business (`StaffHours`) | 1 | 236 | 262 | 0 | — |
| `salaries_india` | education_business (`SalaryDataset`) | 1 | 4,344 | 8,688 | 1 | — |
| `legislators` | city_legislation (`legislators*`) | 3 | 86,896 | 100,107 | 4 | — |
| `jobpostings` | city_legislation (`job_*`, `skills_*`) | 4 | 459,758 | 459,758 | 1 | — |
| `aliens` | city_legislation (`alien*`) | 4 | 200,000 | 100,000 | 1 | — |
| `cities` | city_legislation (`cities*`) | 4 | 45,725 | 45,966 | 4 | — |
| `unicorns` | modern_data (`companies_*`) | 3 | 3,255 | 2,181 | 2 | — |
| `nyctrees` | modern_data (`trees`, `income_trees`) | 2 | 690,846 | 1,374,766 | 2 | — |
| `covidstates` | modern_data (`statistics`) | 1 | 1,010 | 1,010 | 0 | — |
| `wordlist` | modern_data (`word_list`) | 1 | 373,804 | 373,804 | 2 | — |
| `stacking` | stacking | 7 | 10,297 | 10,297 | 3 | — |
| `oraclesql` | oracle_sql | 38 | 1,350 | 1,102 | 8 | — |
| `bowling` | BowlingLeague | 11 | 2,156 | 1,988 | 1 | — |
| `entertainment` | EntertainmentAgency | 13 | 1,654 | 306 | 3 | — |
| `school` | school_scheduling | 15 | 811 | 951 | 1 | — |
| `music` | music | 11 | 15,607 | 15,607 | 1 | — |

Every table of every project round-trips exactly, and every saved query agrees. Most of `bitcoin`'s time is local157's correlated subquery.

Values that are neither text nor exact cents are rebuilt from integers by a rule, never by float arithmetic whose order could change:
- Northwind's float4 money: cents, printed with `%.9g`.
- Chinook's invoice totals: line cents / 100.
- AdventureWorks' 4-decimal money: integers of 1e-4.

## Laws on real data

Run `datagen check --skip-stats` on each ingested dataset. All seven structural checks pass on all thirteen: types, required, unique ids, references, ordering, leakage, anchored. The packs have no laws yet. Stage 2's laws must also pass on these datasets. The research already knows facts that rule out some tempting laws:
- Olist has 1,359 carrier handoffs before approval.
- delivery_center has negative metrics and moments out of order.
- Data Bank customers overdraw: 56.8% end below zero.
- Bitcoin prices break OHLC containment on 2 bars.
- Oracle SH has negative unit costs.
- Pizza Runner order 8 averages 93.6 km/h.
- Sakila customers are created after all their rentals.

A law that real data breaks is wrong, not the data.

## Times the sources do not have

Stage 1 is exact on table contents. For rows with no source time, the time comes from a rule, and stage 2 must not treat it as data:

| Dataset | Rows | Time given by rule |
|---|---|---|
| Olist | final statuses | the last known stage |
| delivery_center | payments | the order's creation |
| delivery_center | deliveries | the `delivering` moment, else the latest earlier moment |
| delivery_center | closes | the `finished` moment, else the last moment |
| Airlines | flight scheduling and cancellation | 30 days before departure |
| Airlines | tickets | the booking time |
| Airlines | check-ins | 130–90 minutes before departure, in boarding order |
| Pizza Runner | deliveries | pickup + duration minutes |
| Pizza Runner | cancellations | the order's time |
| weblog | 19 column-shifted `access_log` rows | the time held in their `session` column |
| weblog | the NULL `invalid_action_log` stamp | the latest earlier stamp in its session |
| weblog | product B001's deletion | the first snapshot's cut, 2016-12-01 |
| weblog | untimed masters (app users, cards, product sales) | 2016-01-01 |
| Chinook, Northwind | customer creation | the first order or invoice (Northwind: N for the 2 with none) |

Every invented time is capped at the snapshot time N.
