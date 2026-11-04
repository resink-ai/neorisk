# parchposey

## What this is

Parch & Posey, a paper company selling standard, gloss and poster paper to large US companies: accounts visit the web site through a channel and place orders; each account has a sales rep, and each rep a region.

Version `v1`, kind `spider2`. The input is one ordered event log of 16,390 events; the output is the 5 source tables, rebuilt exactly, and the answers to 1 saved Spider 2.0 questions.

## Raw data

`education_business.sqlite` (the 5 `web_*` tables). Synthetic course data (Mode Analytics' SQL for Data Analysis course on Udacity); course material with no stated licence.

Times are UTC to the second, stored as `YYYY-MM-DDTHH:MM:SS.000Z`. Region, rep and account creations take rule times.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/parchposey.md`](../../docs/research/spider2/parchposey.md).

## How the log was made

Each web event is a `web_visited` event and each order an `order_placed` event, both owned by the account at their own `occurred_at`. Their source ids are carried (`web_event_id`, `order_id`) and ride as `ord`, because id order is not time order: the orders form two interleaved series. An order carries only its three quantities; `total` and the four `*_amt_usd` columns are rebuilt from them in integer cents (499, 749 and 812 per unit), divided by 100 once. Regions, reps and accounts are entities.

`uv run dataset build parchposey` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `region_created` | entity | 4 | `region_key`, `ext_id`, `name` |
| `sales_reps_created` | entity | 50 | `rep_key`, `ext_id`, `name`, `region_id` |
| `accounts_created` | entity | 351 | `account_key`, `ext_id`, `name`, `website`, `lat`, `long`, `primary_poc`, `sales_rep_id` |
| `web_visited` | business | 9,073 | `account_id`, `web_event_id`, `channel` |
| `order_placed` | business | 6,912 | `account_id`, `order_id`, `standard_qty`, `gloss_qty`, `poster_qty` |

## Times set by rule

Regions and sales reps are created at the catalog start, 2013-12-04 00:00:00, the day of the first event. An account is created at its first web visit; every account has one, and it precedes the account's first order.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `web_region` | 4 | 2 | none |
| `web_sales_reps` | 50 | 3 | none |
| `web_accounts` | 351 | 7 | none |
| `web_events` | 9,073 | 4 | none |
| `web_orders` | 6,912 | 11 | none |

`expected/queries/` holds the answers of the saved questions (`local114`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build parchposey             # → $NEORISK_DATA_ROOT/parchposey/v1/ (default data/datasets/)
uv run dataset verify parchposey            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
