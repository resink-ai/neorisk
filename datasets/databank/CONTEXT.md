# databank

## What this is

Data Bank, a digital bank: customers open accounts, are reassigned between data nodes, and post deposits, purchases and withdrawals.

Version `v1`, kind `spider2`. The input is one ordered event log of 9,873 events; the output is the 3 source tables, rebuilt exactly, and the answers to 6 saved Spider 2.0 questions.

## Raw data

`bank_sales_trading.sqlite` (tables `customer_regions`, `customer_nodes`, `customer_transactions`). Synthetic course data (8 Week SQL Challenge #4); course material.

Dates only; read as midnight UTC. Transactions within a day keep the source rowid order.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/bank_clicklog.md`](../../docs/research/spider2/bank_clicklog.md).

## How the log was made

Each account opening, node reassignment and posted transaction is an event owned by the customer. Regions and customers are entities. Dates only, read as midnight UTC; transactions within a day keep the source rowid order.

`uv run dataset build databank` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `regions_created` | entity | 5 | `region_id`, `ext_id`, `region_name` |
| `customers_created` | entity | 500 | `customer_id`, `ext_id`, `region_id` |
| `account_opened` | business | 500 | `customer_id`, `node_id` |
| `node_reassigned` | business | 3,000 | `customer_id`, `node_id` |
| `transaction_posted` | business | 5,868 | `customer_id`, `txn_type`, `txn_amount`, `src_rowid` |

## Times set by rule

None. Every event time is a source date.

## Snapshot columns

None: every entity attribute travels in its creation event.

| Column | Verdict | Reason |
|---|---|---|
| `regions.ext_id` | creation | The source key (`region_id`). |
| `regions.region_name` | creation | A given name; a static lookup. |
| `customers.ext_id` | creation | The source key (`customer_id`). |
| `customers.created_at` | creation | The first node start date (equal to the first transaction date for 500 of 500); it is the event's time. |
| `customers.region_id` | creation | An immutable ref: every one of a customer's 7 dated node rows, from the first, carries the same region, so the source shows it at creation, not only as of the extract. |

No column qualifies: the node, the one value that changes, already travels on `account_opened` and `node_reassigned`, and balances are derived from `transaction_posted`. There are no snapshot events, so there is no snapshot time N. The creation event keeps `customers_created`: the act of opening is already the `account_opened` event at the same time.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `customer_regions` | 5 | 2 | none |
| `customer_nodes` | 3,500 | 5 | none |
| `customer_transactions` | 5,868 | 4 | none |

`expected/queries/` holds the answers of the saved questions (`local064`, `local074`, `local297`, `local298`, `local299`, `local300`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build databank             # → $NEORISK_DATA_ROOT/databank/v1/ (default data/datasets/)
uv run dataset verify databank            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
