# sakila

## What this is

Sakila (= Pagila), a DVD rental chain: rentals, returns and payments over a film catalogue, with stores, staff and customers.

Version `v1`, kind `spider2`. The input is one ordered event log of 74,314 events; the output is the 16 source tables, rebuilt exactly, and the answers to 9 saved Spider 2.0 questions.

## Raw data

`sqlite-sakila.sqlite`, 16 tables. A generated sample database; BSD licence.

Times end in '.000', read as UTC. last_update is the 2021 load clock; triggers are not replayed.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/pagila.md`](../../docs/research/spider2/pagila.md).

## How the log was made

Rentals start, return and are paid as events owned by the customer. Films (with their category), actors, inventory, addresses and the rest are entities. Each entity's load clock `last_update`, and the attributes that can change after creation (prices, e-mails, phones, active flags, managers), travel in one `<entity>_snapshot` event per row at N. The refs that place a rental (a staff member's store, a copy's store, a customer's address) stay on creation. `film_text` is empty in the source and rebuilt as an empty table.

`uv run dataset build sakila` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `language_created` | entity | 6 | `language_id`, `ext_id`, `name` |
| `country_created` | entity | 109 | `country_id`, `ext_id`, `country` |
| `city_created` | entity | 600 | `city_id`, `ext_id`, `city`, `country_id` |
| `address_created` | entity | 603 | `address_id`, `ext_id`, `address`, `address2`, `district`, `city_id`, `postal_code` |
| `store_created` | entity | 2 | `store_id`, `ext_id` |
| `staff_created` | entity | 2 | `staff_id`, `ext_id`, `first_name`, `last_name`, `store_id`, `username` |
| `customer_created` | entity | 599 | `customer_id`, `ext_id`, `first_name`, `last_name`, `address_id` |
| `actor_created` | entity | 200 | `actor_id`, `ext_id`, `first_name`, `last_name` |
| `category_created` | entity | 16 | `category_id`, `ext_id`, `name` |
| `film_created` | entity | 1,000 | `film_id`, `ext_id`, `title`, `description`, `release_year`, `language_id`, `original_language_id`, `length`, `rating`, `special_features`, `category_id` |
| `film_actor_created` | entity | 5,462 | `film_actor_id`, `ext_id`, `actor_id`, `film_id` |
| `inventory_created` | entity | 4,581 | `inventory_id`, `ext_id`, `film_id`, `store_id` |
| `rental_started` | business | 16,044 | `customer_id`, `rental_id`, `inventory_id`, `staff_id`, `last_update` |
| `payment_taken` | business | 16,049 | `customer_id`, `payment_id`, `rental_id`, `staff_id`, `amount`, `last_update` |
| `rental_returned` | business | 15,861 | `customer_id`, `rental_id` |
| `language_snapshot` | business | 6 | `language_id`, `last_update` |
| `country_snapshot` | business | 109 | `country_id`, `last_update` |
| `city_snapshot` | business | 600 | `city_id`, `last_update` |
| `actor_snapshot` | business | 200 | `actor_id`, `last_update` |
| `category_snapshot` | business | 16 | `category_id`, `last_update` |
| `film_actor_snapshot` | business | 5,462 | `film_actor_id`, `last_update` |
| `inventory_snapshot` | business | 4,581 | `inventory_id`, `last_update` |
| `address_snapshot` | business | 603 | `address_id`, `phone`, `last_update` |
| `store_snapshot` | business | 2 | `store_id`, `manager_staff_id`, `address_id`, `last_update` |
| `staff_snapshot` | business | 2 | `staff_id`, `address_id`, `email`, `active`, `password`, `last_update` |
| `customer_snapshot` | business | 599 | `customer_id`, `store_id`, `email`, `active`, `create_date`, `last_update` |
| `film_snapshot` | business | 1,000 | `film_id`, `rental_duration`, `rental_rate`, `replacement_cost`, `last_update`, `film_category_last_update` |

## Times set by rule

Rentals, payments and returns carry their source times. No entity has a creation time in the source, so every entity is created at the log's first event, 2005-05-24 22:53:30 (the first rental). `customer.create_date` is a load stamp (2006-02-14 22:04:36/37) later than every rental, so it is not a creation time; it is kept as text on the customer snapshot.

Snapshots are at N = 2006-02-15 00:00:00: the latest event (the last rental and payment, 2006-02-14 15:16:03) rounded up to the next whole day, so that `create_date` is also known at N. `last_update` is the port's load clock (2021-03-06), later than N; it is carried verbatim as the source's value, as the research rules.

## Snapshot columns

| Entity | Snapshot event | At (UTC) | Rows | Columns |
|---|---|---|---:|---|
| `language` | `language_snapshot` | 2006-02-15 00:00:00 | 6 | `last_update` |
| `country` | `country_snapshot` | 2006-02-15 00:00:00 | 109 | `last_update` |
| `city` | `city_snapshot` | 2006-02-15 00:00:00 | 600 | `last_update` |
| `actor` | `actor_snapshot` | 2006-02-15 00:00:00 | 200 | `last_update` |
| `category` | `category_snapshot` | 2006-02-15 00:00:00 | 16 | `last_update` |
| `film_actor` | `film_actor_snapshot` | 2006-02-15 00:00:00 | 5,462 | `last_update` |
| `inventory` | `inventory_snapshot` | 2006-02-15 00:00:00 | 4,581 | `last_update` |
| `address` | `address_snapshot` | 2006-02-15 00:00:00 | 603 | `phone`, `last_update` |
| `store` | `store_snapshot` | 2006-02-15 00:00:00 | 2 | `manager_staff_id`, `address_id`, `last_update` |
| `staff` | `staff_snapshot` | 2006-02-15 00:00:00 | 2 | `address_id`, `email`, `active`, `password`, `last_update` |
| `customer` | `customer_snapshot` | 2006-02-15 00:00:00 | 599 | `store_id`, `email`, `active`, `create_date`, `last_update` |
| `film` | `film_snapshot` | 2006-02-15 00:00:00 | 1,000 | `rental_duration`, `rental_rate`, `replacement_cost`, `last_update`, `film_category_last_update` |

| Column | Verdict | Reason |
|---|---|---|
| `*.ext_id` (every entity) | creation | The source key. |
| `*.last_update` (every entity) | snapshot | A modification stamp: the load clock, set by triggers on every insert or update. |
| `language.name` | creation | A given name. |
| `country.country` | creation | A given name. |
| `city.city` | creation | A given name. |
| `city.country_id` | creation | An immutable ref. |
| `address.address`, `address2`, `district`, `postal_code` | creation | The address itself: a different address is a different row. |
| `address.city_id` | creation | An immutable ref, part of the address. |
| `address.phone` | snapshot | A phone, which can change while the address stays (`' '` on every row). |
| `store.manager_staff_id` | snapshot | The manager held now, a role that can change. |
| `store.address_id` | snapshot | Where the store is now; no event or question reads it. |
| `staff.first_name`, `last_name` | creation | Given names. |
| `staff.username` | creation | The login given when the account was made. |
| `staff.store_id` | creation | Kept: it places every rental and payment the staff member takes (local199 counts rentals per store through it), so moving it would give past rentals a store from N. |
| `staff.address_id`, `email` | snapshot | An address and an e-mail. |
| `staff.active` | snapshot | A current active flag. |
| `staff.password` | snapshot | A credential, changeable. |
| `customer.first_name`, `last_name` | creation | Given names. |
| `customer.address_id` | creation | Kept: it places every rental of the customer (local039 groups rentals by the customer's city), so moving it would give past rentals an address from N. |
| `customer.store_id` | snapshot | The customer's home store now; no event or question reads it. |
| `customer.email` | snapshot | An e-mail. |
| `customer.active` | snapshot | A current active flag; inactive customers still rent until N (research). |
| `customer.create_date` | snapshot | A load stamp after every rental, not a sign-up time (research), so it is known only as of the extract. |
| `actor.first_name`, `last_name` | creation | Given names. |
| `category.name` | creation | A given name. |
| `film.title`, `description` | creation | Given title and text. |
| `film.release_year` | creation | A release date. |
| `film.language_id`, `original_language_id` | creation | Immutable refs. |
| `film.length` | creation | Fixed with the film. |
| `film.rating` | creation | The certificate the film was released with, its original classification. |
| `film.special_features` | creation | Fixed with the release. |
| `film.category_id` | creation | The original category (film_category, 1:1). |
| `film.rental_duration` | snapshot | Part of the rental terms the chain sets, which can change. Payments carry their own amounts, so no past event takes it from N. |
| `film.rental_rate` | snapshot | A price. |
| `film.replacement_cost` | snapshot | A price. |
| `film.film_category_last_update` | snapshot | film_category's modification stamp. |
| `film_actor.actor_id`, `film_id` | creation | Immutable refs: the row is the pair. |
| `inventory.film_id` | creation | An immutable ref. |
| `inventory.store_id` | creation | Kept: it places every rental of the copy, so moving it would give past rentals a store from N. |

The research carried every column on its entity; the moves above follow the rubric. `rental.last_update` and `payment.last_update` are load clocks too, but they ride on business events, not entities, so they stay there.

No domain name: no entity has a source creation time (all are created at the log's start by rule), so none shows a sign-up, a hire or a release; every entity keeps `<entity>_created`.

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
