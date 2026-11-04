# staffhours

## What this is

A clock-in/clock-out log: staff members `A` to `Z` record an `Enter` or an `Exit` at a date and minute.

Version `v1`, kind `spider2`. The input is one ordered event log of 262 events; the output is the 1 source table, rebuilt exactly. No Spider 2.0 question reads it, so there are 0 saved questions.

## Raw data

`education_business.sqlite` (the `StaffHours` table, 236 rows, 2013-01-02 to 2013-03-12). Origin unknown, licence unstated; it looks like a SQL-puzzle fixture. It is generated: in rowid order the member is the next letter for 213 of 235 rows and the type alternates Enter/Exit for 223 of 235, but the dates were drawn at random, so in time order the Enters and Exits do not pair.

Dates and `HH:MM` times, read as UTC, on a 5-minute grid.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/edu_misc.md`](../../docs/research/spider2/edu_misc.md).

## How the log was made

Each row is one `staff_clocked` event owned by its staff member, at its own date and minute, with `direction` (`Enter` or `Exit`, the source `EventType`) and its source rowid as `ord`. Staff members are entities.

`uv run dataset build staffhours` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `staff_created` | entity | 26 | `staff_id`, `ext_id` |
| `staff_clocked` | business | 236 | `staff_id`, `direction`, `date_text`, `src_rowid` |

## Times set by rule

A staff member is created at its first clock event. One source row (rowid 100, `V`, `Exit` at 14:40) has the impossible date `2013-02-29`. Its event time is SQLite's normalisation of that text, 2013-03-01 14:40; the event carries `date_text = '2013-02-29'`, which is written back verbatim. For every other row `date_text` is NULL.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `StaffHours` | 236 | 4 | none |

`expected/queries/` is empty: no saved question reads this table. `dataset verify` runs `specs/build.sql` over the log, loads the table into SQLite with the source's DDL, and compares it exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build staffhours             # → $NEORISK_DATA_ROOT/staffhours/v1/ (default data/datasets/)
uv run dataset verify staffhours            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`; the source's Enters and Exits do not pair, so it should not teach shift structure.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
