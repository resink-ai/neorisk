# salaries_india

## What this is

India data-science salaries: Glassdoor listings, each the average salary reported for one company, job title and city.

Version `v1`, kind `spider2`. The input is one ordered event log of 8,688 events; the output is the source table, rebuilt exactly, and the answer to 1 saved Spider 2.0 question.

## Raw data

`education_business.sqlite` (the `SalaryDataset` table, 4,344 rows). Real, scraped, pre-aggregated data: its columns and size match the public Kaggle dataset "Salary Dataset – Data Science and Analytics Industry (India)"; the author, date and licence are unverified. 5 cities, 26 job titles, 2,529 companies. `index` is a pandas RangeIndex (rowid − 1).

The table has no time column. Every time is a rule.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/edu_misc.md`](../../docs/research/spider2/edu_misc.md).

## How the log was made

Each row is a `salary_listing` entity (company, job title, city; `ext_id` is `index`) and one `salary_aggregate_reported` event owned by that listing, which carries what was reported: the number of salaries and the average salary. The `Salary` text, such as `₹6,48,573/yr`, is split into a currency (`₹`, `$`, `£` or `AFN `), an integer amount and a period (`yr`, `mo` or `hr`); the build reprints the amount with Indian lakh grouping (the last 3 digits, then pairs), which reproduces all 4,344 values byte for byte, the `$` and `£` ones included. `SalariesReported` is REAL in the source but always integral; it travels as an integer.

`uv run dataset build salaries_india` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `salary_listing_created` | entity | 4,344 | `listing_id`, `ext_id`, `company_name`, `job_title`, `location` |
| `salary_aggregate_reported` | business | 4,344 | `listing_id`, `salaries_reported`, `salary_currency`, `salary_amount`, `salary_period` |

## Times set by rule

Every listing is created, and its aggregate reported, at 2022-01-01 00:00:00, the dataset's nominal publication year (unverified). The collection window is unknown. Events at that one instant keep `index` order. There are no snapshot events, so there is no snapshot time N.

## Snapshot columns

None: every entity attribute travels in its creation event.

| Column | Verdict | Reason |
|---|---|---|
| `salary_listing.ext_id` | creation | The source key (`index`). |
| `salary_listing.company_name` | creation | A given name; part of what identifies the listing. |
| `salary_listing.job_title` | creation | The title the listing was created for, not a title held by a person; part of what identifies the listing. |
| `salary_listing.location` | creation | The city the listing was created for; part of what identifies the listing. |

No column qualifies: a listing is defined by its company, title and city, and the only values known as of the extract (the number of salaries and the average) already travel on `salary_aggregate_reported`, not on the entity. The creation event keeps `salary_listing_created`: the source shows no real-world act, and every listing is created by rule.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `SalaryDataset` | 4,344 | 6 | none |

`expected/queries/` holds the answers of the saved questions (`local253`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

local253 has no gold SQL and three gold CSVs that clean the salary three different ways. The saved query reproduces `local253_a`: strip the non-numeric characters, annualise `/mo` × 12 and `/hr` × 2,080, keep every currency, and take the national mean over all rows (915,555.247007).

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build salaries_india             # → $NEORISK_DATA_ROOT/salaries_india/v1/ (default data/datasets/)
uv run dataset verify salaries_india            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`; with no event process, the most it can do is draw listings by city, title and company with a salary and period mix.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
