# weblog

## What this is

A web and app product: access, action, purchase and error logs with user, card and product masters (a textbook sample).

Version `v1`, kind `spider2`. The input is one ordered event log of 851 events; the output is the 19 source tables, rebuilt exactly, and the answers to 5 saved Spider 2.0 questions.

## Raw data

`log.sqlite`, all 19 tables. Book sample data with no stated licence.

Times to the second, read as UTC. Rule times: shifted access rows, 1 NULL stamp, 1 deletion, untimed masters.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/weblog.md`](../../docs/research/spider2/weblog.md).

## How the log was made

Every log row is an event, written back in source row order; users register, categories are named and products are updated or deleted through events too, and the product snapshots are rebuilt from those. App users, user cards and product sales figures are entities. Their e-mails, phones, card numbers and sales totals are known only as of the extract, so they travel on `<entity>_snapshot` events at N, not on creation. The creation events keep `<entity>_created`: these masters are untimed, so no real-world act is recorded.

`uv run dataset build weblog` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `app1_users_created` | entity | 2 | `app1_users_key`, `ext_id`, `name` |
| `app2_users_created` | entity | 2 | `app2_users_key`, `ext_id`, `name` |
| `user_cards_created` | entity | 3 | `user_card_key`, `ext_id` |
| `product_sales_created` | entity | 10 | `product_sales_key`, `ext_id`, `category_name` |
| `app1_users_snapshot` | business | 2 | `app1_users_key`, `email` |
| `app2_users_snapshot` | business | 2 | `app2_users_key`, `phone` |
| `user_cards_snapshot` | business | 3 | `user_card_key`, `card_number` |
| `product_sales_snapshot` | business | 10 | `product_sales_key`, `sales` |
| `access_logged` | business | 30 | `user_id`, `session`, `action`, `shifted`, `path_in_stamp`, `src_rowid` |
| `action_logged` | business | 120 | `session`, `user_id`, `action`, `category`, `products`, `amount`, `src_rowid` |
| `action_with_ip_logged` | business | 12 | `session`, `user_id`, `action`, `ip`, `src_rowid` |
| `noisy_action_logged` | business | 0 | `session`, `action`, `products`, `url`, `ip`, `user_agent`, `src_rowid` |
| `dup_action_logged` | business | 11 | `session`, `user_id`, `action`, `products`, `src_rowid` |
| `invalid_action_logged` | business | 7 | `stamp_null`, `session`, `user_id`, `action`, `category`, `products`, `amount`, `src_rowid` |
| `activity_logged` | business | 244 | `session`, `action`, `option`, `path`, `search_type`, `src_rowid` |
| `read_logged` | business | 15 | `session`, `action`, `url`, `src_rowid` |
| `form_viewed` | business | 45 | `session`, `action`, `path`, `status`, `src_rowid` |
| `form_error_logged` | business | 8 | `session`, `form`, `field`, `error_type`, `value`, `src_rowid` |
| `purchase_logged` | business | 5 | `user_id`, `purchase_id`, `amount`, `src_rowid` |
| `user_registered` | business | 320 | `user_id`, `sex`, `birth_date`, `register_device`, `withdraw_date`, `src_rowid` |
| `category_named` | business | 8 | `id`, `name`, `src_rowid` |
| `product_updated` | business | 8 | `product_id`, `name`, `price` |
| `product_deleted` | business | 1 | `product_id` |

## Times set by rule

19 column-shifted `access_log` rows take the time held in their `session` column; the NULL `invalid_action_log` stamp takes the latest earlier stamp in its session; product B001's deletion is the first snapshot's cut, 2016-12-01; untimed masters (app users, cards, product sales) are created at 2016-01-01; snapshots are at N = 2017-03-02 10:00:00, the latest time in the file (a purchase_log stamp).

## Snapshot columns

| Entity | Snapshot event | At (UTC) | Rows | Columns |
|---|---|---|---:|---|
| `app1_users` | `app1_users_snapshot` | 2017-03-02 10:00:00 | 2 | `email` |
| `app2_users` | `app2_users_snapshot` | 2017-03-02 10:00:00 | 2 | `phone` |
| `user_cards` | `user_cards_snapshot` | 2017-03-02 10:00:00 | 3 | `card_number` |
| `product_sales` | `product_sales_snapshot` | 2017-03-02 10:00:00 | 10 | `sales` |

| Column | Verdict | Reason |
|---|---|---|
| `app1_users.ext_id` | creation | The source key (`user_id`). |
| `app1_users.name` | creation | A given name. |
| `app1_users.email` | snapshot | An e-mail, known only as of the extract. |
| `app2_users.ext_id` | creation | The source key (`user_id`). |
| `app2_users.name` | creation | A given name. |
| `app2_users.phone` | snapshot | A phone. |
| `user_cards.ext_id` | creation | The source key (`user_id`). |
| `user_cards.card_number` | snapshot | A card on file can be added or replaced after the user exists (NULL means none on file at the extract); when in doubt, snapshot. |
| `product_sales.ext_id` | creation | The source key (`product_id`). |
| `product_sales.category_name` | creation | The category the product was created in; the source shows no change. |
| `product_sales.sales` | snapshot | A lifetime total no log in the file derives (D001 has 50000; action_log's D001 revenue is 1000s). |

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `mst_users` | 320 | 6 | none |
| `action_log` | 120 | 7 | none |
| `activity_log` | 244 | 6 | none |
| `read_log` | 15 | 4 | none |
| `form_log` | 45 | 5 | none |
| `form_error_log` | 8 | 6 | none |
| `action_log_with_ip` | 12 | 5 | none |
| `access_log` | 30 | 4 | none |
| `action_log_with_noise` | 0 | 7 | none |
| `invalid_action_log` | 7 | 7 | none |
| `mst_categories` | 8 | 3 | none |
| `dup_action_log` | 11 | 5 | none |
| `mst_products_20161201` | 6 | 4 | none |
| `mst_products_20170101` | 6 | 4 | none |
| `app1_mst_users` | 2 | 3 | none |
| `app2_mst_users` | 2 | 3 | none |
| `mst_users_with_card_number` | 3 | 2 | none |
| `purchase_log` | 5 | 4 | none |
| `product_sales` | 10 | 3 | none |

`expected/queries/` holds the answers of the saved questions (`local329`, `local330`, `local331`, `local358`, `local360`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build weblog             # → $NEORISK_DATA_ROOT/weblog/v1/ (default data/datasets/)
uv run dataset verify weblog            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
