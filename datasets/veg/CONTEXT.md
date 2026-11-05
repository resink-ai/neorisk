# veg

## What this is

Vegetable wholesale: one supermarket's vegetable point-of-sale lines, daily wholesale quotes and per-item loss rates, 2020-07-01 to 2023-06-30.

Version `v1`, kind `spider2`. The input is one ordered event log of 934,993 events; the output is the 4 source tables, rebuilt exactly, and the answers to 2 saved Spider 2.0 questions.

## Raw data

`bank_sales_trading.sqlite` (the 4 `veg_*` tables: `veg_txn_df`, `veg_whsle_df`, `veg_cat`, `veg_loss_rate_df`). Real point-of-sale data, released anonymised as Problem C of the 2023 China Undergraduate Mathematical Contest in Modeling (CUMCM); the licence is unstated.

POS lines to the second, read as UTC. Quotes have a date only. `discount(%)` is 1 in all 878,503 rows.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/veg.md`](../../docs/research/spider2/veg.md).

## How the log was made

Each POS line is an event owned by its item: `item_sold` when the quantity is positive, `item_returned` when it is negative (461 lines). Each daily wholesale quote is a `wholesale_price_quoted` event on its item. Categories and items are entities. An item's loss rate, one figure for the whole period, rides on one `items_snapshot` event per item at N.

Every REAL sits on an integer grid and travels as that integer: quantities in grams, selling prices in jiao (0.1 RMB), wholesale prices in fen (as `amount("CNY")`), loss rates in basis points. Each comes back by one division. A POS line keeps the source `index` as `src_index` and as its `ord`: within a second, no column explains the source order. The `index` columns of the other three tables are sort positions and are rebuilt by `row_number()`. `day_of_week` and `sale/return` are derived; `veg_loss_rate_df.item_name` is a copy of `veg_cat.item_name`. The 5,295 POS lines that duplicate another on every data column are each their own event.

`uv run dataset build veg` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `categories_created` | entity | 6 | `category_key`, `ext_id`, `category_name` |
| `items_created` | entity | 251 | `item_key`, `ext_id`, `item_name`, `category_key` |
| `wholesale_price_quoted` | business | 55,982 | `item_key`, `price` |
| `item_sold` | business | 878,042 | `item_key`, `qty_g`, `unit_price_jiao`, `discount_pct`, `src_index` |
| `item_returned` | business | 461 | `item_key`, `qty_g`, `unit_price_jiao`, `discount_pct`, `src_index` |
| `items_snapshot` | business | 251 | `item_key`, `loss_rate_bp` |

## Times set by rule

Categories are created at the catalog start, 2020-07-01 00:00:00. Items are created at their first wholesale quote. Quotes are at 00:00 of their day, before that day's first sale (the earliest is 08:14:12).

N = 2023-06-30 21:40:48, the last POS line. `items_snapshot` is at N; no event is later.

## Snapshot columns

| Entity | Snapshot event | At (UTC) | Rows | Columns |
|---|---|---|---:|---|
| `items` | `items_snapshot` | 2023-06-30 21:40:48 | 251 | `loss_rate_bp` |

| Column | Verdict | Reason |
|---|---|---|
| `categories.category_code` (`ext_id`), `category_name` | creation | The key and its given name. |
| `items.item_code` (`ext_id`) | creation | The key, a barcode. |
| `items.item_name` | creation | A given name. `veg_loss_rate_df.item_name` is a copy of it (251 of 251), rebuilt from the creation. |
| `items.category_code` | creation | The category the item was listed under, one per item. |
| `items.loss_rate_%` (`loss_rate_bp`) | snapshot | One rate per item for the whole three years, a statistic known only at the end of the period (research §2). The previous build carried it on the creation. |

No snapshot column decides an event's time: items are created at their first wholesale quote. The rebuild LEFT JOINs `items_snapshot` on the item key.

No domain name: categories are created at the catalog start and items at their first quote, both rules, not a real-world act the source shows, so both keep `<entity>_created`.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `veg_txn_df` | 878,503 | 9 | none |
| `veg_whsle_df` | 55,982 | 4 | none |
| `veg_cat` | 251 | 5 | none |
| `veg_loss_rate_df` | 251 | 4 | none |

`expected/queries/` holds the answers of the saved questions (`local284`, `local285`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte. Neither question has gold SQL; both are written from the question text and match gold CSV `_b` (local285 reads `discount(%)` as a 1% discount).

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build veg             # → $NEORISK_DATA_ROOT/veg/v1/ (default data/datasets/)
uv run dataset verify veg            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
