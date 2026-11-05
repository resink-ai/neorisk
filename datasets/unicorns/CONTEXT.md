# unicorns

## What this is

The unicorn companies list: 1,074 private companies valued at $1B or more, each with the date it became a unicorn, its industry, its valuation, its total funding and its notable investors.

Version `v1`, kind `spider2`. The input is one ordered event log of 2,181 events; the output is the 3 source tables, rebuilt exactly, and the answers to 2 saved Spider 2.0 questions.

## Raw data

`modern_data.sqlite` (the 3 `companies_*` tables). Real data: a public snapshot of CB Insights' list, distributed by Maven Analytics, in the split of DataCamp's "Analyzing unicorn companies" project. The project's `companies` table (name, city, country) is not in Spider2. Licence: unstated.

Join dates are midnight, read as UTC. The snapshot and the duplicate markers are at a rule time.

Spider2 prepended 11 copies of existing rows to each table, rows 1 to 11, a different set of companies in each table. They are kept: local049's accepted `_a` answer depends on them.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/unicorns.md`](../../docs/research/spider2/unicorns.md).

## How the log was made

Each company is an entity created on the day it joined the list, by a `company_became_unicorn` event carrying its industry and founding year. Its valuation, funding and investors are values as of the list's date, not as of joining, so they travel in one `companies_snapshot` event per company at time N. Each of Spider2's 33 copied rows is a `source_row_duplicated` event naming the company and the table; the views add one more copy of that company's row to that table. Stage 2 can drop that event type and keep the rest.

`uv run dataset build unicorns` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `company_became_unicorn` | entity | 1,074 | `company_key`, `ext_id`, `industry`, `year_founded` |
| `companies_snapshot` | business | 1,074 | `company_id`, `valuation`, `funding`, `select_investors` |
| `source_row_duplicated` | business | 33 | `company_id`, `src_table` |

## Times set by rule

The snapshot and the duplicate markers are at N = 2022-04-05 00:00:00, the last join date. The list's real "as of" date is not in the data.

## Snapshot columns

| Entity | Snapshot event | At (UTC) | Rows | Columns |
|---|---|---|---:|---|
| `companies` | `companies_snapshot` | 2022-04-05 00:00:00 | 1,074 | `valuation`, `funding`, `select_investors` |

| Column | Verdict | Reason |
|---|---|---|
| `companies.ext_id` | creation | The source key (`company_id`). |
| `companies.created_at` (`date_joined`) | creation | The day the company joined the list; it is the event's time. |
| `companies.industry` | creation | The original category the company was listed under; the source shows no change. |
| `companies.year_founded` | creation | A founding date, fixed before the join. |
| `companies.valuation` | snapshot | The current valuation, as of the list's date, not as of joining. |
| `companies.funding` | snapshot | A lifetime total as of the list's date; no log in the file derives it. |
| `companies.select_investors` | snapshot | The investor list as of the list's date; rounds after the join add to it. |

The creation event is `company_became_unicorn`: joining the list is the real-world act, and the source dates it.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `companies_funding` | 1,085 | 4 | none |
| `companies_dates` | 1,085 | 3 | none |
| `companies_industries` | 1,085 | 2 | none |

`expected/queries/` holds the answers of the saved questions (`local049`, `local049_b`), computed on the source. They are the two accepted readings of one question: `local049` joins the raw rows of all three tables (60.333333, gold `_a`), and `local049_b` deduplicates first (57.666667, gold `_b`). `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build unicorns             # → $NEORISK_DATA_ROOT/unicorns/v1/ (default data/datasets/)
uv run dataset verify unicorns            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
