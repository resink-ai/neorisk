# Validation datasets

Each folder is one dataset: **an ordered event log in, organized tables out.** A processor (DuckDB, Spark, Flink or a stream processor) reads only the log, builds the tables, and is graded against the expected ones exactly. The design is [`docs/superpowers/specs/2026-11-03-validation-datasets-design.md`](../docs/superpowers/specs/2026-11-03-validation-datasets-design.md).

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset list                  # the catalogue, and which versions are built here
uv run dataset build olist           # → $NEORISK_DATA_ROOT/olist/v1/ (default data/datasets/)
uv run dataset verify olist          # exit 0 = the reference build over the log matches
uv run dataset resolve olist/v1/log  # where a data name lives under the root
```

## A dataset

| In the repo, `datasets/<name>/` | Holds |
|---|---|
| `dataset.toml` | Name, version, kind (`spider2` or `synthetic`), recipe, the mixed columns, the float columns compared bit for bit |
| `CONTEXT.md` | What the raw data is, how the log was made, the expected output, how to regenerate and extend it |
| `specs/` | Spider2: `pack.py`, `source.toml`, `ingest.sql`, `build.sql` (the reference build), `queries/`. Synthetic: `<design>.sql` for each of three designs, and `questions/<id>/` (`oracle.sql` plus one answer per design) |
| `<version>.lock.json` | Every file's sha256 and rows, the recipe and source sha256 and the writer libraries. Every Spider2 dataset has a committed `v1.lock.json`; a build that differs fails, so changed output needs a new version |

| On the data root, `<name>/<version>/` | Holds |
|---|---|
| `log/part-NNNNN.parquet` | The input: `seq`, `event_time`, `event_type`, `entity_type`, `entity_key`, `schema_version`, `payload` (a JSON object), in `seq` order |
| `schema/events.json` | Every event type and its payload fields, with types |
| `results/<table>.parquet` | The expected tables |
| `expected/queries/<id>.parquet` | Spider2: the saved questions' answers on the source |
| `expected/questions/<id>.parquet`, `labels.parquet`, `cases.parquet`, `check.json` | Synthetic: each question's answer from simkit's own tables, the run's ground truth (never in the log) and its laws and expectations report |
| `schema/results.json`, `manifest.json` | The results' DDL, keys and types; every file's sha256 and rows |

Entities enter the log as events. Each entity row is a creation event, `<entity>_created`, or a domain name given with `-- entity: <name> event=<event_name>` (for example `employee_hired`). Columns known only as of the extract (prices, addresses, statuses, stamps, current names) leave the creation event. They travel in one `<entity>_snapshot` event per row at the dataset's snapshot time N. The build checks that every snapshot is keyed by its entity, that there is one per key, and that all of them share one N that no other event follows. Each dataset's `CONTEXT.md` lists every entity column's verdict (creation or snapshot) with its reason; `uv run dataset context <name>` prints the counted tables.

The suffix `_snapshot` is reserved: an event named `<entity>_snapshot` must follow the snapshot rule above, and no other event may end in `_snapshot`.

### Synthetic datasets

A synthetic dataset's `dataset.toml` names its `datagen` project and run under `[recipe]` (`project`, `profile = "sample"`, `seed = 7`, `overlay = []`) and its three `designs`. `[recipe.owners]` says which payload column keys each event's messages. `dataset build` runs the pack, writes the log, runs each `specs/<design>.sql` over the log alone, and then grades the results twice without trusting them:

- **Against simkit:** every `[[check]]` maps a results table's columns (optionally filtered) to a simkit table's columns, and they must be equal as multisets. Every star dimension and every star fact except the `*_lifecycle` snapshots has one.
- **Across designs:** every question's `oracle.sql` answers it from simkit's own tables, and every design must give the same answer from its own tables only.

`dataset verify` rebuilds every design from the log and checks the tables and all the answers again.

## Table designs

Each synthetic dataset is modeled three ways, picked from the designs compared in the *Beyond Facts & Dimensions* atlas, so one dataset tests a processor on three shapes of output. Every table's name starts with its design id.

| Id | Design | Tables | History |
|---|---|---|---|
| `star` | Star schema (Kimball) | `star_dim_<entity>`, `star_fact_<process>`, `star_fact_<grain>_lifecycle` | SCD2 (`<entity>_sk`, `valid_from`, `valid_to`, `is_current`) where the log changes an attribute; facts carry the version in force at event time; an accumulating snapshot where a lifecycle exists |
| `dv` | Data Vault 2.0 | `dv_hub_<entity>`, `dv_link_<relation>`, `dv_sat_<parent>_<group>` | `md5` hash keys, insert-only, a satellite row only when its `hashdiff` changes, load time = event time |
| `an` | Anchor modeling | `an_<entity>`, `an_<entity>_<attribute>`, `an_<e1>_<role>_<e2>` | one row per attribute change, with `changed_at` |
| `act` | Activity schema | `act_<entity>_stream`, `act_<entity>` | one row per activity: `activity_id, ts, customer, activity, feature_1..3, revenue_impact, link, activity_occurrence, activity_repeated_at` |
| `obt` | One big table | `obt_<grain>` | one wide row per grain, every attribute bound as of the fact's time |

| Dataset | Designs |
|---|---|
| `ecommerce` | `star`, `dv`, `an` |
| `payments` | `star`, `dv`, `obt` |
| `payments_subscriptions` | `star`, `act`, `an` |
| `crypto_exchange` | `star`, `dv`, `obt` |
| `layer1` | `star`, `act`, `obt` |
| `social` | `star`, `dv`, `act` |

Results columns are int32, int64, float64, string, bool, date or timestamp(µs, UTC); a `sum()` must be cast, because DuckDB's HUGEINT fails the build. A new design is a new `specs/<design>.sql` plus an answer to every question, and it makes a new version.

**Extending a dataset:** changing its log, schema or results makes a new version. Copy the recipe to `version = "v2"` in `dataset.toml`, change the specs, then run `dataset build <name> --record`. Editing `CONTEXT.md` needs no new version.

Data files never go into git. They are named `<dataset>/<version>/<path>` and resolved against `NEORISK_DATA_ROOT`, so a remote root later changes one setting.

## The catalogue

| Dataset | Kind | Source | Nature | Licence | Log events | Tables | Result rows | Questions | Mixed columns | Engines passing |
|---|---|---|---|---|---:|---:|---:|---:|---:|---|
| [`databank`](databank/CONTEXT.md) | spider2 | bank_sales_trading | synthetic course data | course material | 9,873 | 3 | 9,373 | 6 | 0 | duckdb |
| [`cliquebait`](cliquebait/CONTEXT.md) | spider2 | bank_sales_trading | synthetic course data | course material | 34,537 | 5 | 34,537 | 1 | 0 | duckdb |
| [`olist`](olist/CONTEXT.md) | spider2 | E_commerce | real, anonymised | CC BY-NC-SA 4.0 | 1,990,875 | 11 | 1,559,764 | 12 | 0 | duckdb, spark, flink, flink-stream |
| [`delivery_center`](delivery_center/CONTEXT.md) | spider2 | delivery_center | real, anonymised | "© original authors" | 3,955,707 | 7 | 1,154,523 | 3 | 0 | duckdb |
| [`airlines`](airlines/CONTEXT.md) | spider2 | Airlines | generated | demo database | 2,340,773 | 8 | 2,289,506 | 2 | 0 | duckdb |
| [`sakila`](sakila/CONTEXT.md) | spider2 | sqlite-sakila | generated sample | BSD | 74,314 | 16 | 46,273 | 9 | 0 | duckdb, spark, flink, flink-stream |
| [`bitcoin`](bitcoin/CONTEXT.md) | spider2 | bank_sales_trading | generated trades, real prices | course material | 26,352 | 3 | 26,336 | 2 | 0 | duckdb |
| [`weblog`](weblog/CONTEXT.md) | spider2 | log | textbook sample | book sample data | 868 | 19 | 854 | 5 | 0 | duckdb |
| [`pizzarunner`](pizzarunner/CONTEXT.md) | spider2 | modern_data | synthetic course data | course material | 55 | 10 | 78 | 3 | 0 | duckdb, spark, flink, flink-stream |
| [`chinook`](chinook/CONTEXT.md) | spider2 | chinook | generated sample | MIT | 19,177 | 11 | 15,607 | 3 | 0 | duckdb |
| [`northwind`](northwind/CONTEXT.md) | spider2 | northwind | generated sample | MIT (Microsoft) | 4,387 | 15 | 3,366 | 2 | 0 | duckdb |
| [`oraclesh`](oraclesh/CONTEXT.md) | spider2 | complex_oracle | generated sample | MIT (Oracle) | 1,123,926 | 10 | 1,064,608 | 6 | 0 | duckdb |
| [`adventureworks`](adventureworks/CONTEXT.md) | spider2 | AdventureWorks | generated sample | MIT (Microsoft) | 200,832 | 13 | 168,686 | 1 | 8 | duckdb |
| [`ipl`](ipl/CONTEXT.md) | spider2 | IPL | real sports data | unstated | 150,986 | 8 | 293,471 | 11 | 0 | duckdb |
| [`f1`](f1/CONTEXT.md) | spider2 | f1 | real public sports results | unstated (Ergast terms unverified) | 687,472 | 29 | 1,941,243 | 9 | 0 | duckdb |
| [`veg`](veg/CONTEXT.md) | spider2 | bank_sales_trading (`veg_*`) | real POS data, anonymised | unstated (contest data) | 934,993 | 4 | 934,987 | 2 | 0 | duckdb |
| [`datamart`](datamart/CONTEXT.md) | spider2 | bank_sales_trading (`weekly_sales`) | generated course data | unstated | 17,117 | 2 | 34,234 | 2 | 0 | duckdb |
| [`freshsegments`](freshsegments/CONTEXT.md) | spider2 | bank_sales_trading (`interest_*`) | course data | unstated | 17,400 | 2 | 15,482 | 2 | 0 | duckdb |
| [`switrs`](switrs/CONTEXT.md) | spider2 | California_Traffic_Collision | real, administrative | CC0 (Kaggle) | 565,814 | 4 | 471,571 | 3 | 0 | duckdb |
| [`eusoccer`](eusoccer/CONTEXT.md) | spider2 | EU_soccer | real, scraped | ODbL 1.0 (unverified) | 233,856 | 7 | 222,796 | 5 | 0 | duckdb |
| [`wwe`](wwe/CONTEXT.md) | spider2 | WWE | real, scraped | unstated | 128,303 | 9 | 578,890 | 1 | 0 | duckdb |
| [`dbimdb`](dbimdb/CONTEXT.md) | spider2 | Db-IMDB | real, scraped | unstated (IMDb content) | 177,621 | 13 | 154,676 | 5 | 0 | duckdb |
| [`imdb_movies`](imdb_movies/CONTEXT.md) | spider2 | imdb_movies | real IMDb data, course-curated | unstated (IMDb content) | 96,023 | 7 | 75,898 | 2 | 0 | duckdb |
| [`baseball`](baseball/CONTEXT.md) | spider2 | Baseball | real records, pre-aggregated | CC BY-SA 3.0 (Lahman) | 574,277 | 26 | 553,693 | 2 | 90 | duckdb |
| [`atliq`](atliq/CONTEXT.md) | spider2 | education_business (`hardware_*`) | generated course data | unstated | 973,234 | 6 | 973,813 | 2 | 0 | duckdb |
| [`parchposey`](parchposey/CONTEXT.md) | spider2 | education_business (`web_*`) | generated course data | unstated | 16,791 | 5 | 16,390 | 1 | 0 | duckdb |
| [`university`](university/CONTEXT.md) | spider2 | education_business (`university_*`) | hand-made course data | unstated | 145 | 5 | 76 | 1 | 0 | duckdb |
| [`staffhours`](staffhours/CONTEXT.md) | spider2 | education_business (`StaffHours`) | generated | unstated | 262 | 1 | 236 | 0 | 0 | duckdb |
| [`salaries_india`](salaries_india/CONTEXT.md) | spider2 | education_business (`SalaryDataset`) | real, scraped, pre-aggregated | unstated | 8,688 | 1 | 4,344 | 1 | 0 | duckdb |
| [`legislators`](legislators/CONTEXT.md) | spider2 | city_legislation (`legislators*`) | real public records | CC0 (upstream) | 112,625 | 3 | 86,896 | 4 | 0 | duckdb |
| [`jobpostings`](jobpostings/CONTEXT.md) | spider2 | city_legislation (`job_*`, `skills_*`) | real, scraped | unstated | 473,761 | 4 | 459,758 | 1 | 0 | duckdb |
| [`aliens`](aliens/CONTEXT.md) | spider2 | city_legislation (`alien*`) | generated | unstated | 100,000 | 4 | 200,000 | 1 | 0 | duckdb |
| [`cities`](cities/CONTEXT.md) | spider2 | city_legislation (`cities*`) | course data, real city facts | unstated | 90,588 | 4 | 45,725 | 4 | 0 | duckdb |
| [`unicorns`](unicorns/CONTEXT.md) | spider2 | modern_data (`companies_*`) | real snapshot, rounded | unstated | 2,181 | 3 | 3,255 | 2 | 0 | duckdb |
| [`nyctrees`](nyctrees/CONTEXT.md) | spider2 | modern_data (`trees`, `income_trees`) | real census | unstated | 1,374,982 | 2 | 690,846 | 2 | 0 | duckdb |
| [`covidstates`](covidstates/CONTEXT.md) | spider2 | modern_data (`statistics`) | real, pre-aggregated | unstated | 1,010 | 1 | 1,010 | 0 | 0 | duckdb |
| [`wordlist`](wordlist/CONTEXT.md) | spider2 | modern_data (`word_list`) | English word list | unstated | 373,804 | 1 | 373,804 | 2 | 0 | duckdb |
| [`stacking`](stacking/CONTEXT.md) | spider2 | stacking | real experiment output | unstated | 10,297 | 7 | 10,297 | 3 | 0 | duckdb |
| [`oraclesql`](oraclesql/CONTEXT.md) | spider2 | oracle_sql | hand-made course data | freeware, not redistributable | 1,102 | 38 | 1,350 | 8 | 0 | duckdb |
| [`bowling`](bowling/CONTEXT.md) | spider2 | BowlingLeague | course data | unstated | 2,032 | 11 | 2,156 | 1 | 0 | duckdb |
| [`entertainment`](entertainment/CONTEXT.md) | spider2 | EntertainmentAgency | course data | unstated | 476 | 13 | 1,654 | 3 | 0 | duckdb |
| [`school`](school/CONTEXT.md) | spider2 | school_scheduling | course data | unstated | 1,119 | 15 | 811 | 1 | 0 | duckdb |
| [`music`](music/CONTEXT.md) | spider2 | music | real catalogue, generated sales | MIT | 19,177 | 11 | 15,607 | 1 | 0 | duckdb |
| [`ecommerce`](ecommerce/CONTEXT.md) | synthetic | `examples/ecommerce` (sample, seed 7) | simulated | generated | 15,090 | 63 | 76,717 | 3 | 0 | duckdb |
| [`payments`](payments/CONTEXT.md) | synthetic | `examples/payments` (sample, seed 7) | simulated | generated | 28,917 | 40 | 56,838 | 3 | 0 | duckdb, spark, flink, flink-stream |
| [`payments_subscriptions`](payments_subscriptions/CONTEXT.md) | synthetic | `examples/payments_subscriptions` (sample, seed 7) | simulated | generated | 2,452 | 30 | 15,422 | 3 | 0 | duckdb |
| [`crypto_exchange`](crypto_exchange/CONTEXT.md) | synthetic | `examples/crypto_exchange` (sample, seed 7) | simulated | generated | 24,055 | 21 | 108,018 | 3 | 0 | duckdb |
| [`layer1`](layer1/CONTEXT.md) | synthetic | `examples/layer1` (sample, seed 7) | simulated | generated | 11,003 | 13 | 30,048 | 3 | 0 | duckdb |
| [`social`](social/CONTEXT.md) | synthetic | `examples/social` (sample, seed 7) | simulated | generated | 25,892 | 18 | 80,174 | 3 | 0 | duckdb |

## Engines

Every dataset runs on `duckdb`, the reference. `pizzarunner`, `sakila`, `olist` and `payments` are also ported to Spark and Flink. An engine reads only the log, writes one Parquet table per results table into a run folder, and is graded against `results/` with the same comparator as `dataset verify`.

| Engine | How | Reads | Port |
|---|---|---|---|
| `duckdb` | in-process, 4 threads | log Parquet | `specs/` (the reference) |
| `spark` | PySpark 4.2.0, `local[4]`, 3 GB driver | log Parquet; payload by `from_json` | `engines/spark/` |
| `flink` | Flink 2.2.1 SQL, batch, Docker | log Parquet; payload by `JSON_VALUE` | `engines/flink/` |
| `flink-stream` | Flink 2.2.1 SQL, streaming, Docker | the log replayed into one Redpanda topic in `seq` order; each table's changelog folded | `engines/flink/` (the same port) |

```bash
uv sync --all-packages --extra engines          # pyspark and confluent-kafka (never --package: it uninstalls the rest)
NEORISK_DATA_ROOT=$PWD/data/datasets docker compose -f apps/dataset/docker/compose.yaml up -d   # Redpanda, Flink, its SQL gateway (~8 GB caps)
uv run dataset run sakila --engine flink-stream # one run → $NEORISK_DATA_ROOT/_runs/sakila/v1/flink-stream/<run-id>/run.json
uv run dataset bench pizzarunner sakila olist payments   # every engine, one at a time → _runs/bench/<run-id>/report.html
docker compose -f apps/dataset/docker/compose.yaml down    # when done
```

`dataset` never starts or stops Docker; a Flink run with the cluster down exits 2 and prints the command above. The containers mount the data root at the same path, so a run's data root must be the one the cluster was started with. Each run records its wall time (split into load, build and write where the engine allows), peak memory (the process tree plus the engine's containers), events per second, and for each table pass or fail, the row counts and a sample of differing rows. `dataset list` shows the engines whose latest run passed.

**Benchmark** (`dataset bench pizzarunner sakila olist payments`, run `20261107T040255Z`, this laptop: macOS, 14 cores, 36 GB; each run in its own process). Every run passes every table. Seconds; load is the replay into Redpanda, plan the Flink gateway declaring and planning the blocks, build the queries or the job, write the fold or the Parquet writes (blank where the engine does not split it). Peak MB is the run's process tree plus the engine's containers; an idle Flink cluster holds about 2.5 GB, and Spark's wall time includes starting the JVM (about 3 s).

| Dataset | Events | Engine | Wall | Load | Plan | Build | Write | Peak MB | Events/s |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| pizzarunner | 55 | duckdb | 0.02 | 0.01 | | 0.01 | 0.00 | 92 | 2,479 |
| | | spark | 6.36 | | | 3.06 | | 1,357 | 8 |
| | | flink | 14.47 | | 10.78 | 3.68 | | 3,938 | 3 |
| | | flink-stream | 16.92 | 2.40 | 10.82 | 3.50 | 0.20 | 4,890 | 3 |
| sakila | 74,314 | duckdb | 0.17 | 0.01 | | 0.15 | 0.02 | 129 | 430,478 |
| | | spark | 7.65 | | | 4.36 | | 1,601 | 9,709 |
| | | flink | 24.04 | | 19.78 | 4.10 | | 4,066 | 3,091 |
| | | flink-stream | 31.00 | 3.84 | 20.13 | 6.57 | 0.46 | 5,034 | 2,397 |
| olist | 1,990,875 | duckdb | 1.37 | 0.01 | | 1.14 | 0.22 | 406 | 1,450,634 |
| | | spark | 12.04 | | | 8.66 | | 2,326 | 165,294 |
| | | flink | 20.89 | | 13.91 | 6.97 | | 4,137 | 95,307 |
| | | flink-stream | 62.80 | 7.86 | 14.03 | 24.92 | 15.99 | 5,459 | 31,703 |
| payments | 28,917 | duckdb | 0.37 | 0.03 | | 0.31 | 0.03 | 242 | 78,027 |
| | | spark | 11.86 | | | 8.35 | | 2,226 | 2,437 |
| | | flink | 45.87 | | 40.06 | 5.80 | | 4,013 | 630 |
| | | flink-stream | 57.25 | 8.83 | 40.51 | 7.30 | 0.61 | 5,036 | 505 |

At these sizes the fixed costs dominate: Flink spends most of a run planning one view per event type and block through the gateway (payments has 40 tables), so the ranking says little about throughput on large logs.

**Add an engine port:** copy `specs/build.sql` (or each `specs/<design>.sql`) to `engines/spark/` or `engines/flink/` and translate each `-- table:` block, keeping its name and columns. The views are the same on every engine. Row order never matters, so drop `ORDER BY`. For Flink, avoid OVER windows that do not order by time (ranks, SCD2 `valid_to`): write them as self-joins, and the same port then passes `flink-stream` too. Add `apps/dataset/tests/test_engines_<name>.py` (see pizzarunner's) and an `## Engines` section to the dataset's `CONTEXT.md`, with every table an engine cannot build and why. Ports are outside the recipe hash, so they never change a version.
