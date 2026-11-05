# freshsegments

## What this is

Fresh Segments, an ad-tech firm: a taxonomy of audience interests, and each interest's monthly composition and index value from 07-2018 to 08-2019.

Version `v1`, kind `spider2`. The input is one ordered event log of 16,191 events; the output is the 2 source tables, rebuilt exactly, and the answers to 2 saved Spider 2.0 questions.

## Raw data

`bank_sales_trading.sqlite` (the tables `interest_map` and `interest_metrics`). Course data (8 Week SQL Challenge #8); course material, licence unstated.

`interest_map` has 1,209 interests with their own `created_at` and `last_modified` stamps, to the second, read as UTC. `interest_metrics` has 14,273 rows; `_month`, `_year` and `interest_id` are REAL, as pandas stores a float column with NaNs. 1,194 metric rows have no month, and 1,193 of them have no interest id either.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/freshsegments.md`](../../docs/research/spider2/freshsegments.md).

## How the log was made

Interests are an entity, created at their `created_at`. A `last_modified` later than `created_at` (709 of 1,209) is an `interest_modified` event with no attributes; the other 500 are equal to `created_at`. Each metric row is an `interest_metrics_reported` event carrying `month_year`, the interest and the two values. Its owner is the source interest id as text, or the sentinel `'none'` for the 1,193 rows without one, since a NULL owner gives a NULL log key. `ranking` and `percentile_ranking` are rebuilt in `specs/build.sql` as `RANK()` by `index_value` within `month_year` (the NULL month is one group of 1,194) and `round(100 * (1 - ranking / group size), 2)`; `_month` and `_year` come from `month_year`.

`uv run dataset build freshsegments` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant; a month's reports follow the source ranking. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `interests_created` | entity | 1,209 | `interest_key`, `ext_id`, `interest_name`, `interest_summary` |
| `interest_modified` | business | 709 | `interest_key` |
| `interest_metrics_reported` | business | 14,273 | `interest`, `interest_key`, `month_year`, `composition`, `index_value` |

## Times set by rule

A month's metrics are stamped at its close, 00:00 UTC on the first day of the next month. In 188 rows the interest was created during the metric month, so a month-start stamp would reference it before its creation; the close never does. The 1,194 month-less rows are stamped at N = 2019-09-01 00:00:00, the close of 08-2019, which is after the last `last_modified` (2019-08-26 11:24:45). Queries must filter on `month_year`, not on the event time.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `interest_map` | 1,209 | 5 | none |
| `interest_metrics` | 14,273 | 8 | none |

`expected/queries/` holds the answers of the saved questions (`local077`, `local078`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

local078 is Spider2's gold SQL; it groups by interest name, so the two "Pizza Lovers" ids merge (neither is in the top or bottom 10). local077 has no gold SQL; it is written from the question and reproduces `local077_b.csv`.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build freshsegments             # → $NEORISK_DATA_ROOT/freshsegments/v1/ (default data/datasets/)
uv run dataset verify freshsegments            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
