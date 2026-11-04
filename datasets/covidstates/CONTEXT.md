# covidstates

## What this is

COVID-19 by state: daily cumulative cases and deaths for Colorado, Florida, Massachusetts and North Carolina, from 2020-02-01 to 2020-11-11.

Version `v1`, kind `spider2`. The input is one ordered event log of 1,010 events; the output is the 1 source table, rebuilt exactly. No Spider 2.0 question reads this table, so there are no saved questions.

## Raw data

`modern_data.sqlite` (the `statistics` table). Real daily state-level surveillance data; the publisher is not identifiable from the data. Licence: unstated.

Report dates are midnight, read as UTC. The duplicate markers are at a rule time.

Each state's series starts at 1 case and has no missing days: CO 251 days, FL 253, MA 285, NC 211. Spider2 prepended 10 copies of existing rows, rows 1 to 10. They are kept.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/modern_misc.md`](../../docs/research/spider2/modern_misc.md).

## How the log was made

Each state-day is one `daily_totals_reported` event, owned by the state, at the report date. It carries the cumulative totals as reported, not daily deltas: the totals fall on 5 days for cases and 8 for deaths (reporting corrections), so deltas would need an invented corrective event. No finer grain exists. Each of Spider2's 10 copied rows is a `source_row_duplicated` event naming the state and date, owned by the sentinel `src_table = 'statistics'`; the view adds one more copy of that row. Stage 2 can drop that event type and keep the rest.

`uv run dataset build covidstates` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Business events keep their columns. The log is in `seq` order: event time, then block order at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `daily_totals_reported` | business | 1,000 | `state`, `total_cases`, `total_deaths` |
| `source_row_duplicated` | business | 10 | `src_table`, `date`, `state` |

## Times set by rule

The duplicate markers are at N = 2020-11-11 00:00:00, the last report date. Every other time is the source's report date.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `statistics` | 1,010 | 4 | none |

There are no saved questions. `dataset verify` runs `specs/build.sql` over the log, loads the table into SQLite with the source's DDL, and compares it exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build covidstates             # → $NEORISK_DATA_ROOT/covidstates/v1/ (default data/datasets/)
uv run dataset verify covidstates            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
