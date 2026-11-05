# atliq

## What this is

AtliQ Hardware, a computer-hardware maker that sells to retailers, distributors and its own stores: monthly sales per product and customer, plus yearly prices, manufacturing costs and customer discounts.

Version `v1`, kind `spider2`. The input is one ordered event log of 973,234 events; the output is the 6 source tables, rebuilt exactly, and the answers to 2 saved Spider 2.0 questions.

## Raw data

`education_business.sqlite` (the 6 `hardware_*` tables). Synthetic course data (Codebasics Resume Project Challenge #4); course material with no stated licence.

Sales dates are the first of the month, read as UTC midnight. Prices, costs, discounts and entity creations take rule times.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/atliq.md`](../../docs/research/spider2/atliq.md).

## How the log was made

The sales table is a pre-aggregate: each row, one month's quantity of one product to one customer, is a `monthly_sales_reported` event owned by the customer at that month's first day. The gross price and the manufacturing cost of a (product, fiscal year) share their 579 keys, so each pair is one `product_priced` event. Each customer's yearly pre-invoice discount is a `customer_deduction_set` event. Customers and products are entities. Prices, costs and discounts have at most 4 decimals and travel as integers of 1e-4 units. A sale's `fiscal_year` is not carried, because it is derived from its month.

`uv run dataset build atliq` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `customers_created` | entity | 209 | `customer_key`, `ext_id`, `customer`, `platform`, `channel`, `market`, `sub_zone`, `region` |
| `products_created` | entity | 397 | `product_key`, `ext_id`, `division`, `segment`, `category`, `product`, `variant` |
| `product_priced` | business | 579 | `product_id`, `fiscal_year`, `gross_price`, `manufacturing_cost` |
| `customer_deduction_set` | business | 418 | `customer_id`, `fiscal_year`, `pre_invoice_discount_pct` |
| `monthly_sales_reported` | business | 971,631 | `customer_id`, `product_id`, `sold_quantity` |

## Times set by rule

The fiscal year starts in September: fiscal year N starts at (N−1)-09-01. Prices, costs and discounts for fiscal year N are set at (N−1)-09-01. Customers are created at the catalog start, 2019-09-01. A product is created at the start of the first fiscal year it is priced in (2019-09-01 for 245 products, 2020-09-01 for 102); the 50 products never priced or sold are created at 2019-09-01. A sale's `fiscal_year` is its calendar year, plus one from September on.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `hardware_dim_customer` | 209 | 7 | none |
| `hardware_dim_product` | 397 | 6 | none |
| `hardware_fact_gross_price` | 579 | 3 | none |
| `hardware_fact_manufacturing_cost` | 579 | 3 | none |
| `hardware_fact_pre_invoice_deductions` | 418 | 3 | none |
| `hardware_fact_sales_monthly` | 971,631 | 5 | none |

`expected/queries/` holds the answers of the saved questions (`local058`, `local059`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build atliq             # → $NEORISK_DATA_ROOT/atliq/v1/ (default data/datasets/)
uv run dataset verify atliq            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
