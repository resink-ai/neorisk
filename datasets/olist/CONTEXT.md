# olist

## What this is

Olist, a Brazilian marketplace: orders with items, payments, approval, carrier handoff, delivery and reviews, plus the seller-acquisition funnel (qualified and won leads).

Version `v1`, kind `spider2`. The input is one ordered event log of 1,990,875 events; the output is the 11 source tables, rebuilt exactly, and the answers to 12 saved Spider 2.0 questions.

## Raw data

`E_commerce.sqlite`, 11 tables. Real, anonymised data from Kaggle (Olist); licence CC BY-NC-SA 4.0, so anything derived from it needs a licence review before commercial use.

Times are São Paulo wall clock (with DST), stored as if UTC. Money is exact cents.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/olist.md`](../../docs/research/spider2/olist.md).

## How the log was made

Each order stage is an event owned by the order, and each lead stage by the lead; sellers, products, geolocation and category translations are entities. A seller's address, and a product's listing text lengths, photo count, weight and measures, ride on one `<entity>_snapshot` event per source row at N. The buyer's address is the order's own, on `order_placed`. Times are São Paulo wall clock stored as if UTC; money is exact cents.

`uv run dataset build olist` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `sellers_created` | entity | 3,095 | `seller_key`, `ext_id` |
| `products_created` | entity | 32,951 | `product_key`, `ext_id`, `category` |
| `geolocation_created` | entity | 1,000,163 | `geo_key`, `ext_id`, `zip_code_prefix`, `lat`, `lng`, `city`, `state` |
| `translations_created` | entity | 71 | `translation_key`, `ext_id`, `english` |
| `sellers_snapshot` | business | 3,095 | `seller_id`, `zip_code_prefix`, `city`, `state` |
| `products_snapshot` | business | 32,951 | `product_id`, `name_length`, `description_length`, `photos_qty`, `weight_g`, `length_cm`, `height_cm`, `width_cm` |
| `lead_qualified` | business | 8,000 | `mql_id`, `landing_page_id`, `origin` |
| `lead_won` | business | 842 | `mql_id`, `seller_ext_id`, `sdr_id`, `sr_id`, `business_segment`, `lead_type`, `lead_behaviour_profile`, `has_company`, `has_gtin`, `average_stock`, `business_type`, `declared_product_catalog_size`, `declared_monthly_revenue` |
| `order_placed` | business | 99,441 | `order_id`, `customer_id`, `customer_unique_id`, `zip_code_prefix`, `city`, `state`, `estimated_delivery` |
| `order_line_added` | business | 112,650 | `order_id`, `order_item_id`, `product_key`, `seller_key`, `price`, `freight_value` |
| `payment_recorded` | business | 103,886 | `order_id`, `payment_sequential`, `payment_type`, `payment_installments`, `payment_value` |
| `order_approved` | business | 99,281 | `order_id` |
| `seller_ship_deadline_set` | business | 100,010 | `order_id`, `seller_key`, `shipping_limit_date` |
| `order_handed_to_carrier` | business | 97,658 | `order_id` |
| `order_delivered` | business | 96,476 | `order_id` |
| `order_status_final` | business | 1,857 | `order_id`, `order_status` |
| `review_requested` | business | 99,224 | `review_id`, `order_id` |
| `review_answered` | business | 99,224 | `review_id`, `order_id`, `review_score`, `review_comment_title`, `review_comment_message` |

## Times set by rule

Final order statuses take the order's last known stage time. Entities have no creation time in the source, so all four are created at the first purchase, 2016-09-04 21:15:19 (the ingest default: the dataset's first time).

N = 2018-11-15 00:00:00, the day after the last event (a `won_date` of 2018-11-14 18:04:19), rounded up to the whole day. Both snapshot events are at N; no event is later.

## Snapshot columns

| Entity | Snapshot event | At (UTC) | Rows | Columns |
|---|---|---|---:|---|
| `sellers` | `sellers_snapshot` | 2018-11-15 00:00:00 | 3,095 | `zip_code_prefix`, `city`, `state` |
| `products` | `products_snapshot` | 2018-11-15 00:00:00 | 32,951 | `name_length`, `description_length`, `photos_qty`, `weight_g`, `length_cm`, `height_cm`, `width_cm` |

| Column | Verdict | Reason |
|---|---|---|
| `sellers.seller_id` (`ext_id`) | creation | The key. |
| `sellers.seller_zip_code_prefix`, `seller_city`, `seller_state` | snapshot | Ruling: the seller's current address; a seller can move, and the row is as of the extract. Research put them on the entity row as static. |
| `products.product_id` (`ext_id`) | creation | The key. |
| `products.product_category_name` | creation | The original category the product was listed with. |
| `products.product_name_lenght`, `product_description_lenght`, `product_photos_qty` | snapshot | Ruling: the listing's title, description and photos as of the extract; a seller edits them. Research called them static. |
| `products.product_weight_g`, `product_length_cm`, `product_height_cm`, `product_width_cm` | snapshot | Ruling: the package measures the seller declared on the listing, as of the extract, and editable; when in doubt, snapshot. No event copies them: the order line keeps its own `freight_value`. Research called them static. |
| `geolocation.*` (`zip_code_prefix`, `lat`, `lng`, `city`, `state`; source rowid as `ext_id`) | creation | A fixed reference lookup of points per ZIP prefix, kept verbatim with its duplicates (research §3). |
| `translations.product_category_name` (`ext_id`), `product_category_name_english` | creation | A fixed name lookup. |
| `customers.customer_zip_code_prefix`, `customer_city`, `customer_state` | kept on `order_placed` | Not an entity: `customer_id` is per order, and the address is the order's own delivery address. 252 of the 2,997 people with more than one order have different addresses on different orders, so one value at N would overwrite each order's own with a later one. |

No snapshot column decides an event's time. The rebuild LEFT JOINs each snapshot on the entity key; the joins from order lines to `products` and `sellers` are unchanged.

No domain name: the source shows no sign-up or listing time for sellers or products (only 380 sellers have a `lead_won`), so every entity keeps `<entity>_created`.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `product_category_name_translation` | 71 | 2 | none |
| `sellers` | 3,095 | 4 | none |
| `customers` | 99,441 | 5 | none |
| `geolocation` | 1,000,163 | 5 | none |
| `order_items` | 112,650 | 7 | none |
| `order_payments` | 103,886 | 5 | none |
| `order_reviews` | 99,224 | 7 | none |
| `orders` | 99,441 | 8 | none |
| `products` | 32,951 | 9 | none |
| `leads_qualified` | 8,000 | 4 | none |
| `leads_closed` | 842 | 14 | none |

`expected/queries/` holds the answers of the saved questions (`local002`, `local003`, `local004`, `local028`, `local029`, `local030`, `local031`, `local032`, `local034`, `local035`, `local037`, `local286`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

## Engines

Ported to every engine: `engines/spark/build.sql` (Spark SQL) and `engines/flink/build.sql` (Flink SQL, run by both `flink` and `flink-stream`). All 11 tables pass on each.

- **Both:** every join is `ON`, not `USING`: the views share key names (`order_id`, `seller_key`, `product_key`) across events. Cent amounts are cast to DOUBLE before `/ 100`, since a decimal literal gives a DECIMAL in Spark and Flink but a DOUBLE in DuckDB. Times are `DATE_FORMAT(..., 'yyyy-MM-dd HH:mm:ss')` in UTC (`yyyy-MM-dd` for `first_contact_date`); categories are cast to STRING.
- **Size:** the largest log ported so far (1,990,875 events, half of them `geolocation_created`). On one laptop run, Spark took 12 s, batch Flink 20 s and `flink-stream` 63 s (most of it replaying the log into Redpanda); the TaskManager peaked at 2.3 GiB of its 4 GiB, with no restart. The streaming joins are plain equi-joins, so their state stays within the cap.

```bash
uv run dataset run olist --engine spark          # flink, flink-stream: the cluster must be up
```

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build olist             # → $NEORISK_DATA_ROOT/olist/v1/ (default data/datasets/)
uv run dataset verify olist            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
