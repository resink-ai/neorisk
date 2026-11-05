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
| `specs/` | Spider2: `pack.py`, `source.toml`, `ingest.sql`, `build.sql` (the reference build), `queries/` |
| `<version>.lock.json` | Every file's sha256 and rows, the recipe and source sha256 and the writer libraries. Every Spider2 dataset has a committed `v1.lock.json`; a build that differs fails, so changed output needs a new version |

| On the data root, `<name>/<version>/` | Holds |
|---|---|
| `log/part-NNNNN.parquet` | The input: `seq`, `event_time`, `event_type`, `entity_type`, `entity_key`, `schema_version`, `payload` (a JSON object), in `seq` order |
| `schema/events.json` | Every event type and its payload fields, with types |
| `results/<table>.parquet` | The expected tables |
| `expected/queries/<id>.parquet` | Spider2: the saved questions' answers on the source |
| `schema/results.json`, `manifest.json` | The results' DDL, keys and types; every file's sha256 and rows |

Entities enter the log as events. Each entity row is a creation event, `<entity>_created`, or a domain name given with `-- entity: <name> event=<event_name>` (for example `employee_hired`). Columns known only as of the extract (prices, addresses, statuses, stamps, current names) leave the creation event. They travel in one `<entity>_snapshot` event per row at the dataset's snapshot time N. The build checks that every snapshot is keyed by its entity, that there is one per key, and that all of them share one N that no other event follows. Each dataset's `CONTEXT.md` lists every entity column's verdict (creation or snapshot) with its reason; `uv run dataset context <name>` prints the counted tables.

**Extending a dataset:** changing its log, schema or results makes a new version. Copy the recipe to `version = "v2"` in `dataset.toml`, change the specs, then run `dataset build <name> --record`. Editing `CONTEXT.md` needs no new version.

Data files never go into git. They are named `<dataset>/<version>/<path>` and resolved against `NEORISK_DATA_ROOT`, so a remote root later changes one setting.

## The catalogue

| Dataset | Kind | Source | Nature | Licence | Log events | Tables | Result rows | Questions | Mixed columns | Engines passing |
|---|---|---|---|---|---:|---:|---:|---:|---:|---|
| [`databank`](databank/CONTEXT.md) | spider2 | bank_sales_trading | synthetic course data | course material | 9,873 | 3 | 9,373 | 6 | 0 | duckdb |
| [`cliquebait`](cliquebait/CONTEXT.md) | spider2 | bank_sales_trading | synthetic course data | course material | 34,537 | 5 | 34,537 | 1 | 0 | duckdb |
| [`olist`](olist/CONTEXT.md) | spider2 | E_commerce | real, anonymised | CC BY-NC-SA 4.0 | 1,990,875 | 11 | 1,559,764 | 12 | 0 | duckdb |
| [`delivery_center`](delivery_center/CONTEXT.md) | spider2 | delivery_center | real, anonymised | "© original authors" | 3,955,707 | 7 | 1,154,523 | 3 | 0 | duckdb |
| [`airlines`](airlines/CONTEXT.md) | spider2 | Airlines | generated | demo database | 2,340,773 | 8 | 2,289,506 | 2 | 0 | duckdb |
| [`sakila`](sakila/CONTEXT.md) | spider2 | sqlite-sakila | generated sample | BSD | 74,314 | 16 | 46,273 | 9 | 0 | duckdb |
| [`bitcoin`](bitcoin/CONTEXT.md) | spider2 | bank_sales_trading | generated trades, real prices | course material | 26,352 | 3 | 26,336 | 2 | 0 | duckdb |
| [`weblog`](weblog/CONTEXT.md) | spider2 | log | textbook sample | book sample data | 868 | 19 | 854 | 5 | 0 | duckdb |
| [`pizzarunner`](pizzarunner/CONTEXT.md) | spider2 | modern_data | synthetic course data | course material | 55 | 10 | 78 | 3 | 0 | duckdb |
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

The synthetic datasets (from the `datagen` examples) arrive in PR 3, and the Spark and Flink engines in PR 4.
