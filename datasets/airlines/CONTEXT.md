# airlines

## What this is

An airline: flights scheduled, departed, arrived, delayed or cancelled; bookings, tickets, sold segments and check-ins.

Version `v1`, kind `spider2`. The input is one ordered event log of 2,340,773 events; the output is the 8 source tables, rebuilt exactly, and the answers to 2 saved Spider 2.0 questions.

## Raw data

`Airlines.sqlite`, all 8 tables: the Postgres Pro demo database (small edition), a generated snapshot at N = 2017-08-15 18:00+03. Spider2 dropped passenger names and contact data.

Times are '+03' wall clock, stored as if UTC; '\N' text stands for a missing time.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/airlines.md`](../../docs/research/spider2/airlines.md).

## How the log was made

Flight lifecycle events are owned by the flight, bookings and tickets by the booking. Aircraft, airports and seats are entities.

`uv run dataset build airlines` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `aircrafts_created` | entity | 9 | `aircraft_key`, `ext_id`, `model`, `range` |
| `airports_created` | entity | 104 | `airport_key`, `ext_id`, `airport_name`, `city`, `coordinates`, `timezone` |
| `seats_created` | entity | 1,339 | `seat_key`, `ext_id`, `aircraft_key`, `seat_no`, `fare_conditions` |
| `flight_scheduled` | business | 33,121 | `flight_id`, `flight_no`, `scheduled_departure`, `scheduled_arrival`, `departure_airport`, `arrival_airport`, `aircraft_key` |
| `flight_cancelled` | business | 414 | `flight_id` |
| `checkin_opened` | business | 17,324 | `flight_id` |
| `flight_delayed` | business | 41 | `flight_id` |
| `flight_departed` | business | 16,773 | `flight_id` |
| `flight_arrived` | business | 16,715 | `flight_id` |
| `booking_created` | business | 262,788 | `book_ref` |
| `ticket_issued` | business | 366,733 | `ticket_no`, `book_ref`, `passenger_id` |
| `segment_sold` | business | 1,045,726 | `ticket_no`, `book_ref`, `flight_id`, `fare_conditions`, `amount` |
| `passenger_checked_in` | business | 579,686 | `ticket_no`, `flight_id`, `boarding_no`, `seat_no` |

## Times set by rule

Flight scheduling and cancellation are 30 days before departure; tickets take the booking time; check-ins are 130 to 90 minutes before departure, in boarding order.

Aircraft, airports and seats have no creation time in the source, so they are created at the dataset's first time, 2017-06-15 18:50:00 (the ingest default: the earliest `flight_scheduled`).

N = 2017-08-15 18:00:00 (+03), the source's own snapshot time (`bookings.now()`, the latest `book_date` and `actual_arrival`). It caps every invented time. There are no snapshot events, so nothing is placed at N.

## Snapshot columns

None: every entity attribute travels in its creation event.

| Column | Verdict | Reason |
|---|---|---|
| `aircrafts_data.aircraft_code` (`ext_id`) | creation | The key. A code names an aircraft model (the type), not a single airframe. |
| `aircrafts_data.model` | creation | The model's given name (JSON text, en and ru). |
| `aircrafts_data.range` | creation | The model's design range in km, a fixed property of the type, not of a plane's state. |
| `airports_data.airport_code` (`ext_id`) | creation | The key. |
| `airports_data.airport_name` | creation | A given name (JSON text). |
| `airports_data.city` | creation | The city the airport serves (JSON text): its fixed location, not a mailing address that can move. |
| `airports_data.coordinates` | creation | The airport's fixed position, `(lon,lat)`. |
| `airports_data.timezone` | creation | The tz name of the airport's location (17 in all), fixed with the position. |
| `seats.aircraft_code` (`aircraft_key`), `seat_no` | creation | The key: an immutable ref to the model and the seat label. |
| `seats.fare_conditions` | creation | The class the seat was laid out in. Every boarding pass's seat is in the class of its segment (579,686 of 579,686, research §3), so a later re-layout would contradict past check-ins. |

Research classes all three tables as static (§1): there is no stock, no status, no `last_update` and no lifetime total on them. Every per-flight and per-booking state is already its own event or derived: a flight's status and actual times come from its lifecycle events, a booking's `total_amount` is the sum of its `segment_sold` amounts, and seat occupancy is the `passenger_checked_in` seat numbers.

No domain name: the source shows no act that brings an aircraft model, an airport or a seat into being, so each keeps `<entity>_created`.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `aircrafts_data` | 9 | 3 | none |
| `airports_data` | 104 | 5 | none |
| `boarding_passes` | 579,686 | 4 | none |
| `bookings` | 262,788 | 3 | none |
| `flights` | 33,121 | 10 | none |
| `seats` | 1,339 | 3 | none |
| `ticket_flights` | 1,045,726 | 4 | none |
| `tickets` | 366,733 | 3 | none |

`expected/queries/` holds the answers of the saved questions (`local009`, `local010`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build airlines             # → $NEORISK_DATA_ROOT/airlines/v1/ (default data/datasets/)
uv run dataset verify airlines            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
