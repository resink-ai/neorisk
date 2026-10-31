# Reference datasets from Spider 2.0: real tables as simkit event logs

**Status:** draft, 2026-10-30
**Research:** [`docs/research/spider2/`](../../research/spider2/). There is one report per dataset, plus the scripts behind every number in it.

## Why

The `examples/` packs are invented, so nothing tells us whether their data is realistic. Spider 2.0 (`xlang-ai/Spider2`), a widely used text-to-SQL benchmark, ships 30 SQLite databases with their full data, plus questions that show how analysts query them. Some of those databases record real businesses. If we can say exactly which event log produced their tables, we get three things:

1. a simkit pack whose output is anchored to real tables;
2. a validation target that is independent of the simulator: real tables vs tables rebuilt from generated events;
3. the benchmark's questions as ready-made analyses to run on both.

## Two stages

| Stage | What | Pass condition |
|---|---|---|
| **1. Exact round trip** | Real tables → event log (in simkit's dataset layout, conforming to the pack's schema) → tables again | Every table equals the original as a multiset of rows, and every saved benchmark query gives the same result on both |
| **2. Statistical match** | A simkit pack generates the event log; the same views turn it into tables | Distributions, rates and query *shapes* match the real tables within stated tolerances |

Stage 1 comes first. It fixes the event catalog and the views, and those are what stage 2 is graded with. This spec designs stage 1 in detail and leaves stage 2 to one plan per dataset.

## Datasets

The SQLite files come from the Spider2-lite local database zip (436 MB; the link is in `spider2-lite/README.md`). A catalog is not one business: `bank_sales_trading` bundles five course datasets. The unit is therefore a coherent group of tables.

| Project | Source file : tables | Nature | Events (stage 1) | Rows | Licence |
|---|---|---|---|---:|---|
| `olist` | `E_commerce` : orders, order_items, order_payments, order_reviews, customers, sellers, products, geolocation, product_category_name_translation, leads_qualified, leads_closed | real (Kaggle, Olist) | 12 | ≈1.5M (1M of them geolocation) | CC BY-NC-SA 4.0 |
| `delivery_center` | `delivery_center` : all 7 tables | real, anonymised (Kaggle) | 12 | ≈1.15M | "© original authors" |
| `airlines` | `Airlines` : all 8 tables | generated (Postgres Pro demo-small, 2017-08-15) | 10 | ≈2.3M | MIT for the 2025 release; unstated for 2017 |
| `databank` | `bank_sales_trading` : customer_regions, customer_nodes, customer_transactions | synthetic course data (8 Week SQL Challenge #4) | 3 | ≈9.4k | course material |
| `cliquebait` | `bank_sales_trading` : shopping_cart_users, shopping_cart_events, shopping_cart_page_hierarchy, shopping_cart_event_identifier, shopping_cart_campaign_identifier | synthetic course data (#6) | 1 (it is already an event log) | ≈34.5k | course material |

`olist` uses the `E_commerce` copy because it is the only one with the lead funnel. `Brazilian_E_Commerce` and `electronic_sales` hold the same rows (verified), so queries written for them run on `E_commerce` once the `olist_` prefix and `index` columns are mapped.

**Licences decide what is committed.** No raw SQLite files, ingested event logs or rebuilt tables go into git: `data/` is already ignored. The repo holds the specs, the SQL, the analysis reports and, in stage 2, fitted parameters. Before anything derived from `olist` ships commercially, it needs a licence review (NC-SA).

Out of scope: the BigQuery and Snowflake parts of Spider2 (no account), bitcoin, veg_*, weekly_sales, interest_* and every other local database (sports, reference and teaching data).

## Architecture

```text
examples/<project>/                 one project per dataset; stage 2 grows it into a full pack
  datagen.toml                      [run] seed/days (unused in stage 1)
  specs/pack.py                     Config + define(p): entities and events only in stage 1
  specs/source.toml                 source file, tables, each table's key, time zone note
  specs/ingest.sql                  SQLite SQL: one block per event and entity table (tables → log)
  specs/views.sql                   DuckDB SQL: one block per source table (log → tables)
  specs/queries/<id>.sql            saved benchmark questions (SQLite dialect, source table names)
apps/refdata/                       new app: CLI `refdata`
  fetch     download + verify the zip → data/spider2/*.sqlite
  ingest    run ingest.sql → a simkit dataset at data/ref/<project>/
  rebuild   run views.sql over a dataset → a SQLite file with the source DDL
  compare   source vs rebuilt: per-table multiset equality + saved queries
  roundtrip ingest → rebuild → compare, exit 1 on any difference
```

Because an ingested log uses simkit's dataset layout, the existing tools work on it unchanged: `neorisk_simkit.io.read`, `datagen schema --load`, `datagen replay` and the structural checks. Stage 2 runs `rebuild` and `compare` on a *generated* run with the same views; only the comparison's tolerance changes.

### Conventions for an ingested dataset

- **Layout:** `manifest.json` (with `"provenance": {"source": "ingest", "file": …, "sha256": …}`), `schema/schema.json` built from the pack's plan, `events/<type>.parquet` and `entities/<table>.parquet`. There are no labels or cases; those files are written empty, with the schema columns.
- **Common columns:**
  - `event_time`: the source wall-clock time, read as if it were UTC, in µs (see the time row in the table below).
  - `seq`: rank by (event_time, the `ord` value from ingest, the block's position in `ingest.sql`, owner value, the block's own `ORDER BY` row order).
  - `event_id` = `seq`.
  - `partition_id`: the dense rank of the owning entity key named in the block header.
  - `cause_id` is null and `action_id` is 0.
- **Ids:**
  - Every entity table has an i64 key assigned at ingest (dense rank of the source id, in source key order) and an `ext_id` text column holding the source id verbatim.
  - Events reference entities with `ref()` (i64).
  - Source ids that belong to no entity table (e.g. `payment_id`, `ticket_no`) ride on the event as attributes, typed as in the source.
  - In stage 2, the pack writes `ext_id` in the source's format.
- **Values:**
  - Money that is exact cents in the source becomes `amount()` in minor units.
  - Every other float stays `f64`.
  - Text is byte-exact (CR+LF in Olist reviews, trailing spaces in delivery_center store names, the `\N` strings and JSON text in Airlines).
- **Time:** wall clock as UTC everywhere. Olist is São Paulo time with DST (the true-UTC fold breaks on 39 timestamps); delivery_center is UTC; Airlines carries `+03` text, which the views write back. `views.sql` formats times back into each source's exact text format.

### Exactness

`compare` passes when, for every source table:
- the rebuilt table has the same columns;
- its rows equal the source's as a **multiset**: row order is never compared, because the Olist and Airlines files are in generator order;
- values are compared after one normalisation: SQLite INTEGER and REAL compare by numeric value, because delivery_center stores 62 and 62.7 in one DECIMAL column. Text and NULL compare exactly.

The report names the first differing rows per table. Saved queries pass when their result sets are equal under the same rule, ordered when the query has `ORDER BY`.

## Per-dataset decisions (from the research reports)

| Project | Untimed rows get their time from | Carried as attributes because not derivable | Other decisions |
|---|---|---|---|
| `olist` | lines, payments → `order_placed`; ship deadline → approval (else purchase); final status → last known stage, emitted only where the timestamps imply a different status (1,857 orders) | `shipping_limit_date`, `order_estimated_delivery_date`, review text, per-order customer address | geolocation, sellers, products and translation are entity snapshots (geolocation verbatim, with its 261,831 duplicate rows, since query local035 sorts it) |
| `delivery_center` | payments → `order_created`; deliveries → `order_delivering`, else the latest earlier moment; cancel → last non-null moment | all 7 `order_metric_*` values (only about 75% equal `round(Δ/60,2)`); `order_created_*` parts (wrong on 3 rows); `payment_id`, `delivery_id` | moments are emitted in column order with a `stage` attribute, because 1.24% are out of time order |
| `airlines` | tickets, segments → `book_date`; check-in → a rule ordered by `boarding_no`; cancel → `flight_scheduled` time | `flight_id`, `ticket_no`, `book_ref`, `passenger_id`, `seat_no`, `boarding_no`, `actual_*` | the log ends at N = 2017-08-15 18:00+03 inclusive; `flights.status` is the latest status event ≤ N, and Cancelled overrides (8 cancelled flights have actuals) |
| `databank` | — (dates; within a day, ord = source rowid) | — | node end_date = next start − 1 day, else 9999-12-31; no non-negative-balance law (56.8% of customers end negative) |
| `cliquebait` | — (it is the event log) | `visit_id`, `cookie_id`, microsecond text with trailing zeros stripped | `shopping_cart_users` is derived from cookies; a purchase has no product: it means "everything added to the cart in that visit" |

The query checks come from the benchmark questions each report reproduced:

| Project | Questions |
|---|---|
| `olist` | 12 (9 matched gold) |
| `delivery_center` | local209, local210, local212 |
| `airlines` | local009 (local010's gold value looks wrong; keep it, comparing source vs rebuilt rather than against gold) |
| `databank` | local064, local298, local300 and the 3 others on the same tables |
| `cliquebait` | local075 |

### Batch 2 (2026-10-31)

Eight more projects, from the reports `docs/research/spider2/{pagila,bitcoin,weblog,pizzarunner,chinook,northwind,oraclesh,adventureworks}.md`. Same pipeline, same exactness rule; every one is a new `examples/<project>/`.

| Project | Source (tables) | Events / entities | Decisions |
|---|---|---|---|
| `pizzarunner` | modern_data (`pizza_*`, 11 tables) | 4 / 4 | delivered = pickup + duration, cancelled = order time (rules). The `clean_*` and `get_*` tables are rebuilt by views from the raw text: leading-number regexp, default 0.0. Comma lists stay verbatim (`,` in orders, `, ` in recipes). Run window reaches runner 4's registration on 2021-01-15. |
| `bitcoin` | bank_sales_trading (`bitcoin_*`) | 2 / 2 | `price_published` is an exogenous event owned by the ticker. `change` is carried, not computed. `volume` is parsed to whole coins and re-formatted (K below 1,000,000, M from there; `-` kept). ord = `txn_id` for the 28 midnight ties. |
| `chinook` | chinook (11 tables; not `sqlite_sequence`, `sqlite_stat1`) | 2 / 9 | invoice `Total` = Σ line cents / 100.0, never a float sum. Billing address is derived from the customer. |
| `northwind` | northwind (all, the 2 empty demographics tables rebuilt empty) | 3 / 11 | float4 money (freight, unit price, discount) is held in cents or basis points and printed with `printf('%.9g')`. Ship address is carried on the order (it differs on 82). The 21 unshipped orders get no `order_shipped`. |
| `sakila` | sqlite-sakila (16 tables; Pagila.sqlite is byte-identical) | 3 / 12 | `last_update` is a load-time stamp, carried verbatim as text. `film_category` folds into `film`. `film_text` is rebuilt empty. Payment amount is data: the late-fee rule holds on returned rentals only. Triggers are not replayed. |
| `weblog` | log (19 tables) | 15 / 4 | one event per source log; there is no user or session entity, because ids conflict across tables. The 19 column-shifted `access_log` rows, 1 NULL stamp, 1 deletion and 17 untimed rows get rule times. The two product snapshots are rebuilt from 9 change events. `activity_log` ties need ord = source rowid. |
| `oraclesh` | complex_oracle (10 tables; its 3 SQLite views are not data) | 2 / 7 | `unit_sold` per sales row (918,843, quantity always 1); `price_quoted` from costs. `currency` is generated by its exact rule in the view, not stored. 51 placeholder products hold the sold product ids that have no product row. |
| `adventureworks` | AdventureWorks (13 tables) | 6 / 7 | money is 4-decimal: held as integers of 1e-4, subtotal = line sum rounded half-up. `taxamt`, `freight`, YTD counters, rowguids and `currencyrateid` are carried. `''` in numeric columns round-trips through the source DDL's affinity. N = 2014-07-07. |

Queries: every question each report reproduced, with the source-vs-rebuilt comparison as the check, as in batch 1.

## Laws on real data

`datagen check`'s structural checks run on an ingested dataset unchanged. The pack's own laws, which stage 2 adds, also run against the real log. When a law fails on real data, the law is wrong; real data is never the one in error. The research already knows a few: Olist has 1,359 handoffs before approval, delivery_center has negative metrics, and Data Bank has overdrafts. Any law that real data breaks must then be weakened or recorded as a known deviation.

## Stage 2 (later, one plan per project)

Each pack adds owners, machines and sources (sketched in §6 of each report), fitted to the distributions in §5. `refdata compare --stats` then compares generated with real at stage 2 tolerances:
- per-column distribution distance;
- stage-delay quantiles;
- category mixes;
- join cardinalities;
- the saved queries as shape checks (rank order, top-k overlap, ratios), not as values.

Order: `olist` → `delivery_center` → `airlines` → `databank` / `cliquebait`.

## Non-goals and risks

- No change to `libs/simkit`. A schema-only pack already validates, with 0 problems.
- Times that the source never had are chosen by rule: Olist cancels, delivery_center payments and deliveries, Airlines tickets and check-ins. Stage 1 is exact on *table contents*, not on those times, and stage 2 should not treat them as facts.
- Airlines check-in timing rests on 9 flights near N and contradicts the docs' 24-hour window. Treat it as unknown.
- Size: Airlines is about 4M events. Stage 1 is plain Polars and SQL, so this is fine; stage 2 needs a reduced profile (the report suggests about 400k events).
