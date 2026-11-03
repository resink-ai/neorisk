# bitcoin

## What this is

A Bitcoin and Ethereum trading desk: member trades and daily price bars.

Version `v1`, kind `spider2`. The input is one ordered event log of 26,338 events; the output is the 3 source tables, rebuilt exactly, and the answers to 2 saved Spider 2.0 questions.

## Raw data

`bank_sales_trading.sqlite` (the `bitcoin_*` tables). Generated trades over real prices; course material.

Trade times are UTC to the millisecond; price bars are dates, read as midnight UTC.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/bitcoin.md`](../../docs/research/spider2/bitcoin.md).

## How the log was made

Each trade is an event owned by the member, in transaction id order; each daily price bar is a `price_published` event owned by the ticker. Members and tickers are entities. Volume is parsed to an integer and printed back as K or M.

`uv run dataset build bitcoin` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `tickers_created` | entity | 2 | `ticker_id`, `ext_id` |
| `members_created` | entity | 14 | `member_id`, `ext_id`, `first_name`, `region` |
| `price_published` | business | 3,404 | `ticker_id`, `price`, `open`, `high`, `low`, `volume`, … (7 in all) |
| `trade` | business | 22,918 | `member_id`, `ticker_id`, `txn_type`, `quantity`, `percentage_fee`, `txn_id` |

## Times set by rule

None. Prices and trades carry their source dates.

## Snapshot columns

Classified in PR 2. Until then every entity attribute travels in its creation event.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `bitcoin_members` | 14 | 3 | none |
| `bitcoin_transactions` | 22,918 | 8 | none |
| `bitcoin_prices` | 3,404 | 8 | none |

`expected/queries/` holds the answers of the saved questions (`local156`, `local157`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build bitcoin             # → $NEORISK_DATA_ROOT/bitcoin/v1/ (default data/datasets/)
uv run dataset verify bitcoin            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
