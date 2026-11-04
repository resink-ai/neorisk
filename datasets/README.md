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
| `dataset.toml` | Name, version, kind (`spider2` or `synthetic`), recipe, the mixed columns |
| `CONTEXT.md` | What the raw data is, how the log was made, the expected output, how to regenerate and extend it |
| `specs/` | Spider2: `pack.py`, `source.toml`, `ingest.sql`, `build.sql` (the reference build), `queries/` |
| `<version>.lock.json` | Once recorded: every file's sha256 and rows; a build that differs fails |

| On the data root, `<name>/<version>/` | Holds |
|---|---|
| `log/part-NNNNN.parquet` | The input: `seq`, `event_time`, `event_type`, `entity_type`, `entity_key`, `schema_version`, `payload` (a JSON object), in `seq` order |
| `schema/events.json` | Every event type and its payload fields, with types |
| `results/<table>.parquet` | The expected tables |
| `expected/queries/<id>.parquet` | Spider2: the saved questions' answers on the source |
| `schema/results.json`, `manifest.json` | The results' DDL, keys and types; every file's sha256 and rows |

Data files never go into git. They are named `<dataset>/<version>/<path>` and resolved against `NEORISK_DATA_ROOT`, so a remote root later changes one setting.

## The catalogue

| Dataset | Kind | Source | Nature | Licence | Log events | Tables | Result rows | Questions | Mixed columns | Engines passing |
|---|---|---|---|---|---:|---:|---:|---:|---:|---|
| [`databank`](databank/CONTEXT.md) | spider2 | bank_sales_trading | synthetic course data | course material | 9,873 | 3 | 9,373 | 6 | 0 | duckdb |
| [`cliquebait`](cliquebait/CONTEXT.md) | spider2 | bank_sales_trading | synthetic course data | course material | 34,537 | 5 | 34,537 | 1 | 0 | duckdb |
| [`olist`](olist/CONTEXT.md) | spider2 | E_commerce | real, anonymised | CC BY-NC-SA 4.0 | 1,954,829 | 11 | 1,559,764 | 12 | 0 | duckdb |
| [`delivery_center`](delivery_center/CONTEXT.md) | spider2 | delivery_center | real, anonymised | "© original authors" | 3,949,932 | 7 | 1,154,523 | 3 | 0 | duckdb |
| [`airlines`](airlines/CONTEXT.md) | spider2 | Airlines | generated | demo database | 2,340,773 | 8 | 2,289,506 | 2 | 0 | duckdb |
| [`sakila`](sakila/CONTEXT.md) | spider2 | sqlite-sakila | generated sample | BSD | 61,134 | 16 | 46,273 | 9 | 0 | duckdb |
| [`bitcoin`](bitcoin/CONTEXT.md) | spider2 | bank_sales_trading | generated trades, real prices | course material | 26,338 | 3 | 26,336 | 2 | 0 | duckdb |
| [`weblog`](weblog/CONTEXT.md) | spider2 | log | textbook sample | book sample data | 851 | 19 | 854 | 5 | 0 | duckdb |
| [`pizzarunner`](pizzarunner/CONTEXT.md) | spider2 | modern_data | synthetic course data | course material | 55 | 10 | 78 | 3 | 0 | duckdb |
| [`chinook`](chinook/CONTEXT.md) | spider2 | chinook | generated sample | MIT | 15,607 | 11 | 15,607 | 3 | 0 | duckdb |
| [`northwind`](northwind/CONTEXT.md) | spider2 | northwind | generated sample | MIT (Microsoft) | 4,175 | 15 | 3,366 | 2 | 0 | duckdb |
| [`oraclesh`](oraclesh/CONTEXT.md) | spider2 | complex_oracle | generated sample | MIT (Oracle) | 1,063,399 | 10 | 1,064,608 | 6 | 0 | duckdb |
| [`adventureworks`](adventureworks/CONTEXT.md) | spider2 | AdventureWorks | generated sample | MIT (Microsoft) | 199,389 | 13 | 168,686 | 1 | 8 | duckdb |

The synthetic datasets (from the `datagen` examples) arrive in PR 3, and the Spark and Flink engines in PR 4.
