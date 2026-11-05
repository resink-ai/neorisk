# datamart

## What this is

Data Mart, an online supermarket: weekly sales totals per region, platform (Retail or Shopify), customer segment and customer type, around a packaging change on 2020-06-15.

Version `v1`, kind `spider2`. The input is one ordered event log of 17,117 events; the output is the 2 source tables, rebuilt exactly, and the answers to 2 saved Spider 2.0 questions.

## Raw data

`bank_sales_trading.sqlite` (the tables `weekly_sales` and `cleaned_weekly_sales`). Synthetic course data (8 Week SQL Challenge #5); course material, licence unstated.

The data is pre-aggregated: 72 weeks in three 24-week windows (2018, 2019, 2020) × 7 regions × 2 platforms × 17 segment and type cells, with 19 small Shopify cells missing. There is no finer grain. `week_date` is `d/m/yy` text, read as midnight UTC. The missing segment is SQL NULL (3,024 rows, every Guest row among them).

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/datamart.md`](../../docs/research/spider2/datamart.md).

## How the log was made

Each `weekly_sales` row is one reported event, owned by its region, at its week's Monday. `sales` travels in minor units (the source has whole dollars). `cleaned_weekly_sales` is the case study's cleansing step and produces no events: `specs/build.sql` derives it from the same events, with the ISO week number, `'unknown'` for a NULL segment, age band and demographic from the segment's two characters, and `avg_transaction` as sales / transactions rounded half up to 2 dp by integer division. SQLite's and DuckDB's `round()` each miss some of the 109 exact ties.

`uv run dataset build datamart` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Business events keep their columns. The log is in `seq` order: event time, then region, platform, segment and customer type. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `weekly_sales_reported` | business | 17,117 | `region`, `platform`, `segment`, `customer_type`, `transactions`, `sales` |

## Times set by rule

The source has no reporting time. Each cell is stamped at its `week_date`, the Monday the week starts, at 00:00 UTC, so `week_date` is a pure format of the event time. The snapshot time N is 2020-08-31, the last week.

## Snapshot columns

None: every entity attribute travels in its creation event.

The dataset has no entities, so no column is classified. Regions, platforms, segments and customer types are categorical fields of each weekly cell, not entities: none has an attribute of its own, and every measure (`transactions`, `sales`) is dated to its week, not known only at N. The `cleaned_weekly_sales` columns are derived in `build.sql`.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `weekly_sales` | 17,117 | 7 | none |
| `cleaned_weekly_sales` | 17,117 | 14 | none |

`expected/queries/` holds the answers of the saved questions (`local301`, `local302`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

local301 is Spider2's gold SQL. local302 has no gold SQL; it is written from the question and rounds each attribute value's % change to 3 dp before averaging, which is the only reading that gives the expected −2.008666666667 for `demographic`.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build datamart             # → $NEORISK_DATA_ROOT/datamart/v1/ (default data/datasets/)
uv run dataset verify datamart            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
