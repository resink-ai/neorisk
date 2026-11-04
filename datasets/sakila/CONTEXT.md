# sakila

## What this is

Sakila (= Pagila), a DVD rental chain: rentals, returns and payments over a film catalogue, with stores, staff and customers.

Version `v1`, kind `spider2`. The input is one ordered event log of 61,134 events; the output is the 16 source tables, rebuilt exactly, and the answers to 9 saved Spider 2.0 questions.

## Raw data

`sqlite-sakila.sqlite`, 16 tables. A generated sample database; BSD licence.

Times end in '.000', read as UTC. last_update is the 2021 load clock; triggers are not replayed.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/pagila.md`](../../docs/research/spider2/pagila.md).

## How the log was made

Rentals start, return and are paid as events owned by the customer. Films (with their category), actors, inventory, addresses and the rest are entities. `film_text` is empty in the source and rebuilt as an empty table.

`uv run dataset build sakila` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `language_created` | entity | 6 | `language_id`, `ext_id`, `name`, `last_update` |
| `country_created` | entity | 109 | `country_id`, `ext_id`, `country`, `last_update` |
| `city_created` | entity | 600 | `city_id`, `ext_id`, `city`, `country_id`, `last_update` |
| `address_created` | entity | 603 | `address_id`, `ext_id`, `address`, `address2`, `district`, `city_id`, … (9 in all) |
| `store_created` | entity | 2 | `store_id`, `ext_id`, `manager_staff_id`, `address_id`, `last_update` |
| `staff_created` | entity | 2 | `staff_id`, `ext_id`, `first_name`, `last_name`, `address_id`, `email`, … (11 in all) |
| `customer_created` | entity | 599 | `customer_id`, `ext_id`, `store_id`, `first_name`, `last_name`, `email`, … (10 in all) |
| `actor_created` | entity | 200 | `actor_id`, `ext_id`, `first_name`, `last_name`, `last_update` |
| `category_created` | entity | 16 | `category_id`, `ext_id`, `name`, `last_update` |
| `film_created` | entity | 1,000 | `film_id`, `ext_id`, `title`, `description`, `release_year`, `language_id`, … (16 in all) |
| `film_actor_created` | entity | 5,462 | `film_actor_id`, `ext_id`, `actor_id`, `film_id`, `last_update` |
| `inventory_created` | entity | 4,581 | `inventory_id`, `ext_id`, `film_id`, `store_id`, `last_update` |
| `rental_started` | business | 16,044 | `customer_id`, `rental_id`, `inventory_id`, `staff_id`, `last_update` |
| `payment_taken` | business | 16,049 | `customer_id`, `payment_id`, `rental_id`, `staff_id`, `amount`, `last_update` |
| `rental_returned` | business | 15,861 | `customer_id`, `rental_id` |

## Times set by rule

None. Customers are created at their first event, because the source creation date falls after all their rentals; the source date is kept as text.

## Snapshot columns

Classified in PR 2. Until then every entity attribute travels in its creation event.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `actor` | 200 | 4 | none |
| `country` | 109 | 3 | none |
| `city` | 600 | 4 | none |
| `address` | 603 | 8 | none |
| `language` | 6 | 3 | none |
| `category` | 16 | 3 | none |
| `customer` | 599 | 9 | none |
| `film` | 1,000 | 13 | none |
| `film_actor` | 5,462 | 3 | none |
| `film_category` | 1,000 | 3 | none |
| `film_text` | 0 | 3 | none |
| `inventory` | 4,581 | 4 | none |
| `staff` | 2 | 11 | none |
| `store` | 2 | 4 | none |
| `payment` | 16,049 | 7 | none |
| `rental` | 16,044 | 7 | none |

`expected/queries/` holds the answers of the saved questions (`local038`, `local039`, `local056`, `local193`, `local194`, `local195`, `local196`, `local197`, `local199`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build sakila             # → $NEORISK_DATA_ROOT/sakila/v1/ (default data/datasets/)
uv run dataset verify sakila            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
