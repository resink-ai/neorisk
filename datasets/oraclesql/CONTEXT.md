# oraclesql

## What this is

The `PRACTICAL` demo schema of Kim Berg Hansen's book *Practical Oracle SQL* (Apress, 2020): a fictional craft-beer trader. Breweries deliver purchases that are put away as warehouse lots, customers order, pickers walk FIFO pick lists, and monthly sales and budgets are kept. Beside it are staff hire periods, a webshop's page counters and visits, server heartbeats and a stock ticker.

Version `v1`, kind `spider2`. The input is one ordered event log of 1,102 events; the output is the 38 source tables, rebuilt exactly, and the answers to 8 saved Spider 2.0 questions.

## Raw data

`oracle_sql.sqlite` (all 38 tables, and 11 views). Hand-made, scripted course data from `practical_fill_schema.sql` in `Apress/practical-oracle-sql`; all 33 non-empty tables equal the book script's INSERTs. Freeware licence, some rights reserved: keep it local, do not redistribute.

Dates are `YYYY-MM-DD` and datetimes `YYYY-MM-DD HH:MM:SS`, read as UTC; `server_heartbeat.beat_time` has no seconds. Every REAL column is integral except `product_alcohol.abv` (halves) and `ticker.price` (tenths). 5 tables are empty: `conway_gen_zero`, as upstream, and the 4 tables Spider made from Oracle TYPEs.

The view `emp_hire_periods_with_name` still names `start_date`, which Spider renamed `start_`, so it fails on the source too when read. No saved question reads it.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/oraclesql.md`](../../docs/research/spider2/oraclesql.md).

## How the log was made

Product groups, products (with `product_alcohol` folded in), breweries, customers, packaging and its relations, employees, web apps and pages, the stock and the two dimension tables are 12 entity types, 68 rows. Purchases, lots, monthly sales, budgets, orders and their lines are events on their brewery, product or customer. Pick lists, planned pick lines and the picking log's arrivals, picks and departures are events on the picker, and hire periods start and end on the employee. Counters, visits, heartbeats, device and demographic counts and prices are events on their page, client IP, server, app or stock. Employee titles and supervisors, customer favourite and review lists, and product minimums have no time of their own: they are snapshot events at N. `locations` is the book's generated grid (2 warehouses × aisles A–D × positions 1–32) and is rebuilt by SQL, so `location_id` travels as a plain integer. The 11 views produce no events: `dataset verify` replays their stored SQL over the rebuilt tables before the saved questions run.

`uv run dataset build oraclesql` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `product_groups_created` | entity | 4 | `group_key`, `ext_id`, `name` |
| `products_created` | entity | 10 | `product_key`, `ext_id`, `name`, `group_id`, `sales_volume`, `abv` |
| `breweries_created` | entity | 3 | `brewery_key`, `ext_id`, `name` |
| `customers_created` | entity | 4 | `customer_key`, `ext_id`, `name` |
| `packaging_created` | entity | 11 | `packaging_key`, `ext_id`, `name` |
| `packaging_relations_created` | entity | 12 | `prel_key`, `ext_id`, `packaging_id`, `contains_id`, `qty` |
| `employees_created` | entity | 14 | `employee_key`, `ext_id`, `name` |
| `web_apps_created` | entity | 1 | `app_key`, `ext_id`, `name` |
| `web_pages_created` | entity | 4 | `page_key`, `ext_id`, `app_id`, `page_no`, `friendly_url` |
| `stock_created` | entity | 1 | `stock_key`, `ext_id`, `company` |
| `channels_dim_created` | entity | 2 | `channel_key`, `ext_id`, `name`, `shortcut` |
| `gender_dim_created` | entity | 2 | `gender_key`, `ext_id`, `name` |
| `purchase_received` | business | 180 | `brewery_id`, `purchase_id`, `product_id`, `qty`, `cost` |
| `lot_stored` | business | 113 | `product_id`, `inventory_id`, `location_id`, `purchase_id`, `qty` |
| `monthly_sales_reported` | business | 360 | `product_id`, `qty` |
| `budget_set` | business | 48 | `product_id`, `mth`, `qty` |
| `order_placed` | business | 10 | `customer_id`, `order_id` |
| `order_line_added` | business | 18 | `customer_id`, `orderline_id`, `order_id`, `product_id`, `qty`, `amount` |
| `picklist_created` | business | 2 | `picker_emp_id`, `picklist_id` |
| `pick_line_planned` | business | 21 | `picker_emp_id`, `picklist_id`, `line_no`, `location_id`, `order_id`, `product_id`, `qty` |
| `picker_arrived` | business | 21 | `picker_emp_id`, `picklist_id`, `location_id`, `pickline_no` |
| `line_picked` | business | 21 | `picker_emp_id`, `picklist_id`, `location_id`, `pickline_no` |
| `picker_departed` | business | 21 | `picker_emp_id`, `picklist_id`, `location_id`, `pickline_no` |
| `hire_period_started` | business | 15 | `employee_id`, `title` |
| `hire_period_ended` | business | 8 | `employee_id`, `start` |
| `page_counter_read` | business | 120 | `page_id`, `counter` |
| `page_visited` | business | 23 | `client_ip`, `page_id`, `src_rowid` |
| `heartbeat_received` | business | 14 | `server` |
| `device_counts_reported` | business | 2 | `app_id`, `pc`, `tablet`, `phone` |
| `demographics_reported` | business | 2 | `app_id`, `m_tw_cnt`, `m_tw_qty`, `m_fb_cnt`, `m_fb_qty`, `f_tw_cnt`, `f_tw_qty`, `f_fb_cnt`, `f_fb_qty` |
| `price_quoted` | business | 15 | `stock_id`, `price` |
| `customers_snapshot` | business | 4 | `customer_id`, `favorite_list`, `review_list` |
| `employees_snapshot` | business | 14 | `employee_id`, `title`, `supervisor_id` |
| `products_snapshot` | business | 2 | `product_id`, `qty_minimum`, `qty_purchase` |

## Times set by rule

Masters are created at 2016-01-01, the first purchase; employees at their first hire period's start (6 of 14), else 2016-01-01. Inventory lots take their purchase's date, budgets Jan 1 of their year, and planned pick lines their pick list's creation time. Monthly sales and the daily counters, device and demographic counts are stamped at their period's first instant. The 20 snapshot rows take N = 2019-05-02, the last observed day. The web devices and demographics carry the one web app, 542, as owner.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `customers` | 4 | 2 | none |
| `conway_gen_zero` | 0 | 3 | none |
| `web_devices` | 2 | 4 | none |
| `web_demographics` | 2 | 9 | none |
| `channels_dim` | 2 | 3 | none |
| `gender_dim` | 2 | 2 | none |
| `packaging` | 11 | 2 | none |
| `packaging_relations` | 12 | 3 | none |
| `product_groups` | 4 | 2 | none |
| `products` | 10 | 3 | none |
| `monthly_sales` | 360 | 3 | none |
| `breweries` | 3 | 2 | none |
| `purchases` | 180 | 6 | none |
| `product_alcohol` | 10 | 3 | none |
| `customer_favorites` | 4 | 2 | none |
| `customer_reviews` | 4 | 2 | none |
| `locations` | 256 | 4 | none |
| `inventory` | 113 | 5 | none |
| `orders` | 10 | 4 | none |
| `orderlines` | 18 | 5 | none |
| `monthly_budget` | 48 | 3 | none |
| `product_minimums` | 2 | 3 | none |
| `stock` | 1 | 2 | none |
| `ticker` | 15 | 3 | none |
| `web_apps` | 1 | 2 | none |
| `web_pages` | 4 | 3 | none |
| `web_counter_hist` | 120 | 4 | none |
| `server_heartbeat` | 14 | 2 | none |
| `web_page_visits` | 23 | 4 | none |
| `employees` | 14 | 4 | none |
| `emp_hire_periods` | 15 | 4 | none |
| `picking_list` | 2 | 3 | none |
| `picking_line` | 21 | 6 | none |
| `picking_log` | 63 | 5 | none |
| `id_name_type` | 0 | 2 | none |
| `id_name_coll_type` | 0 | 1 | none |
| `id_name_coll_entries` | 0 | 3 | none |
| `favorite_coll_type` | 0 | 1 | none |

`expected/queries/` holds the answers of the saved questions (`local269`, `local270`, `local272`, `local273`, `local274`, `local275`, `local277`, `local279`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, replays the source views, and compares the tables and the answers exactly: rows as multisets, numbers by value, text byte for byte.

Five questions reproduce a gold variant (local269, local270, local272, local274, local275). local273, local277 and local279 are written from the question text: their golds are degenerate, contradictory or not matched, so their answers are this dataset's reading, still compared exactly between source and rebuild.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build oraclesql             # → $NEORISK_DATA_ROOT/oraclesql/v1/ (default data/datasets/)
uv run dataset verify oraclesql            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table and view names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
