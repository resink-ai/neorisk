# delivery_center

## What this is

Delivery Center, a Brazilian food and goods delivery hub operator, January to April 2021: orders through their stages, payments, deliveries and closes.

Version `v1`, kind `spider2`. The input is one ordered event log of 3,955,707 events; the output is the 7 source tables, rebuilt exactly, and the answers to 3 saved Spider 2.0 questions.

## Raw data

`delivery_center.sqlite`, all 7 tables. Real, anonymised data from Kaggle ("Data files © Original Authors").

Moments are 'M/D/YYYY h:mm:ss AM' text in UTC. Payments and deliveries have no time.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/delivery_center.md`](../../docs/research/spider2/delivery_center.md).

## How the log was made

Each order moment is an `order_stage` event; creation, payments, delivery assignment and closing are events too, all owned by the order. Channels, hubs, stores and drivers are entities. A store's plan price and coordinates, and a driver's modal and type, ride on one `<entity>_snapshot` event per source row at N. Moments are `M/D/YYYY h:mm:ss AM` text in UTC.

`uv run dataset build delivery_center` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `hubs_created` | entity | 32 | `hub_key`, `ext_id`, `hub_name`, `hub_city`, `hub_state`, `hub_latitude`, `hub_longitude` |
| `stores_created` | entity | 951 | `store_key`, `ext_id`, `hub_key`, `store_name`, `store_segment` |
| `channels_created` | entity | 40 | `channel_key`, `ext_id`, `channel_name`, `channel_type` |
| `drivers_created` | entity | 4,824 | `driver_key`, `ext_id` |
| `stores_snapshot` | business | 951 | `store_key`, `store_plan_price`, `store_latitude`, `store_longitude` |
| `drivers_snapshot` | business | 4,824 | `driver_key`, `driver_modal`, `driver_type` |
| `order_created` | business | 368,999 | `order_id`, `store_key`, `channel_key`, `order_amount`, `order_delivery_fee`, `order_created_hour`, `order_created_minute`, `order_created_day`, `order_created_month`, `order_created_year` |
| `order_stage` | business | 2,047,790 | `order_id`, `stage`, `stage_no` |
| `order_closed` | business | 368,999 | `order_id`, `order_status`, `order_delivery_cost`, `order_metric_collected_time`, `order_metric_paused_time`, `order_metric_production_time`, `order_metric_walking_time`, `order_metric_expediton_speed_time`, `order_metric_transit_time`, `order_metric_cycle_time` |
| `payment_recorded` | business | 400,834 | `payment_id`, `order_id`, `payment_amount`, `payment_fee`, `payment_method`, `payment_status` |
| `delivery_assigned` | business | 378,843 | `delivery_id`, `order_id`, `driver_key`, `delivery_distance_meters` |
| `delivery_closed` | business | 378,620 | `delivery_id`, `order_id`, `delivery_status` |

## Times set by rule

Payments take the order's creation; deliveries the `delivering` moment, else the latest earlier one; closes the `finished` moment, else the last one. Entities have no creation time in the source, so all four are created at the first order, 2020-12-31 16:01:36 (the ingest default: the dataset's first time).

N = 2021-05-08 00:00:00, the day after the last event (a `finished` moment of 2021-05-07 16:10:17), rounded up to the whole day. Both snapshot events are at N; no event is later.

## Snapshot columns

| Entity | Snapshot event | At (UTC) | Rows | Columns |
|---|---|---|---:|---|
| `stores` | `stores_snapshot` | 2021-05-08 00:00:00 | 951 | `store_plan_price`, `store_latitude`, `store_longitude` |
| `drivers` | `drivers_snapshot` | 2021-05-08 00:00:00 | 4,824 | `driver_modal`, `driver_type` |

| Column | Verdict | Reason |
|---|---|---|
| `hubs.hub_id` (`ext_id`) | creation | The key. |
| `hubs.hub_name` | creation | A given name: the shopping centre the hub is in. |
| `hubs.hub_city`, `hub_state`, `hub_latitude`, `hub_longitude` | creation | The hub is a fixed site (a named shopping centre); its place is part of what it is, not an address that can move. |
| `stores.store_id` (`ext_id`) | creation | The key. |
| `stores.hub_id` (`hub_key`) | creation | An immutable ref: the hub the store sits in, one per store. Research: dimensions are never mutated. |
| `stores.store_name` | creation | A given name, byte-exact with its trailing spaces. |
| `stores.store_segment` | creation | The original category the store was set up with (FOOD or GOOD). |
| `stores.store_plan_price` | snapshot | Ruling: the price of the store's current plan, as of the extract (115 NULL); prices change. Research called stores static. |
| `stores.store_latitude`, `store_longitude` | snapshot | Ruling: the store's geocoded address as of the extract (16 NULL, the rest at or near the hub's); an address can move or be filled in later, and when in doubt, snapshot. Research called stores static. |
| `channels.channel_id` (`ext_id`) | creation | The key. |
| `channels.channel_name`, `channel_type` | creation | A given name and the original type (MARKETPLACE or OWN CHANNEL). |
| `drivers.driver_id` (`ext_id`) | creation | The key. |
| `drivers.driver_modal` | snapshot | Ruling: the vehicle the driver uses now (BIKER or MOTOBOY); a driver can change it. Research called drivers static. |
| `drivers.driver_type` | snapshot | Ruling: the driver's current contract (FREELANCE or LOGISTIC OPERATOR); a freelancer can join an operator. When in doubt, snapshot. Research called drivers static. |

No snapshot column decides an event's time, and no event copies one: `delivery_assigned` carries only the driver's key, and `order_created` only the store's. The rebuild LEFT JOINs each snapshot on the entity key; the joins from stores to hubs, from orders to stores and channels and from deliveries to drivers are unchanged.

No domain name: the source shows no opening, sign-up or hire time for hubs, stores, channels or drivers, so every entity keeps `<entity>_created`.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `channels` | 40 | 3 | none |
| `drivers` | 4,824 | 3 | none |
| `deliveries` | 378,843 | 5 | none |
| `hubs` | 32 | 6 | none |
| `payments` | 400,834 | 6 | none |
| `stores` | 951 | 7 | none |
| `orders` | 368,999 | 29 | none |

`expected/queries/` holds the answers of the saved questions (`local209`, `local210`, `local212`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build delivery_center             # → $NEORISK_DATA_ROOT/delivery_center/v1/ (default data/datasets/)
uv run dataset verify delivery_center            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
