# pizzarunner

## What this is

Pizza Runner, a pizza delivery start-up: pizzas ordered, picked up by runners, delivered or cancelled.

Version `v1`, kind `spider2`. The input is one ordered event log of 55 events; the output is the 10 source tables, rebuilt exactly, and the answers to 3 saved Spider 2.0 questions.

## Raw data

`modern_data.sqlite` (the 10 `pizza_*` tables). Synthetic course data (8 Week SQL Challenge #2); course material.

Times to the second, read as UTC. Delivery and cancellation times are rules.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/pizzarunner.md`](../../docs/research/spider2/pizzarunner.md).

## How the log was made

Each ordered pizza is an event owned by its order, in source row order; pickups, deliveries and cancellations are events on the order too. Runners, pizzas, toppings and customers are entities. A runner's creation event is `runner_registered`, at its `registration_date`; the source records that act. Customers are created at their first order, which is not a sign-up, so they keep `customers_created`. The clean and helper tables are rebuilt by SQL from the raw ones.

`uv run dataset build pizzarunner` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `runner_registered` | entity | 4 | `runner_id`, `ext_id` |
| `pizzas_created` | entity | 2 | `pizza_id`, `ext_id`, `pizza_name`, `toppings` |
| `toppings_created` | entity | 12 | `topping_id`, `ext_id`, `topping_name` |
| `customers_created` | entity | 5 | `customer_id`, `ext_id` |
| `pizza_ordered` | business | 14 | `order_id`, `customer_id`, `pizza_id`, `exclusions`, `extras`, `src_row` |
| `order_picked_up` | business | 8 | `order_id`, `runner_id` |
| `order_delivered` | business | 8 | `order_id`, `runner_id`, `distance`, `duration` |
| `order_cancelled` | business | 2 | `order_id`, `runner_id`, `cancellation` |

## Times set by rule

Deliveries are pickup + duration minutes; cancellations take the order's time.

There are no snapshot events, so there is no snapshot time N. If one is added, N must be at least 2021-01-15 00:00:00: runner 4 registers then, after the last delivery (2021-01-11 19:00:20).

## Snapshot columns

None: every entity attribute travels in its creation event.

| Column | Verdict | Reason |
|---|---|---|
| `runners.ext_id` | creation | The source key. |
| `runners.created_at` (`registration_date`) | creation | The registration date; it is the event's time. |
| `pizzas.ext_id` | creation | The source key. |
| `pizzas.pizza_name` | creation | A given name. |
| `pizzas.toppings` | creation | The recipe defines the menu item it was created as; the questions apply it to every order line as the recipe at order time, and the source shows no change. |
| `toppings.ext_id` | creation | The source key. |
| `toppings.topping_name` | creation | A given name. |
| `customers.ext_id` | creation | The source key; customers carry no other attribute. |

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `pizza_names` | 2 | 2 | none |
| `pizza_recipes` | 2 | 2 | none |
| `pizza_toppings` | 12 | 2 | none |
| `pizza_runners` | 4 | 2 | none |
| `pizza_customer_orders` | 14 | 6 | none |
| `pizza_clean_customer_orders` | 14 | 6 | none |
| `pizza_runner_orders` | 10 | 6 | none |
| `pizza_clean_runner_orders` | 10 | 6 | none |
| `pizza_get_extras` | 6 | 4 | none |
| `pizza_get_exclusions` | 4 | 4 | none |

`expected/queries/` holds the answers of the saved questions (`local065`, `local066`, `local073`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build pizzarunner             # → $NEORISK_DATA_ROOT/pizzarunner/v1/ (default data/datasets/)
uv run dataset verify pizzarunner            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
