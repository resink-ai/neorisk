# jobpostings

## What this is

Data-job postings scraped from Google Jobs during 2023: each posting, the companies behind them, the skills catalogue, and which skills each posting asks for.

Version `v1`, kind `spider2`. The input is one ordered event log of 459,758 events; the output is the 4 source tables, rebuilt exactly, and the answer to 1 saved Spider 2.0 question.

## Raw data

`city_legislation.sqlite` (the tables `job_postings_fact`, `job_company`, `skills_dim` and `skills_job_dim`). The course database of Luke Barousse's "SQL for Data Analytics" (`company_dim` renamed to `job_company`), with each table an independent ~10% sample: only 7,334 of 78,769 postings find their company, and only 5,590 of 366,960 skill links find both their posting and their skill. The course repo states no licence, and the rows are scraped third-party content.

Times to the second, read as UTC. Postings run from 2022-12-31 06:03:30 to 2023-12-31 03:18:00. Company, skill and link creation are rules.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/jobpostings.md`](../../docs/research/spider2/jobpostings.md).

## How the log was made

Each posting is a `job_posted` event owned by its `job_id`, at `job_posted_date`, with `ord = job_id` among the 2,785 tied times. Companies, skills and the posting-skill links are entities. Because the sampling leaves about 90% of every relation orphaned, `company_id` on a posting and `job_id` and `skill_id` on a link are raw `i64` ids, never refs, and every table is a straight projection of its event or entity. The salaries are float32 artefacts and travel as `f64` verbatim.

`uv run dataset build jobpostings` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `companies_created` | entity | 14,003 | `company_key`, `ext_id`, `name`, `link`, `link_google`, `thumbnail` |
| `skills_created` | entity | 26 | `skill_key`, `ext_id`, `skills`, `type` |
| `job_skills_created` | entity | 366,960 | `job_skill_key`, `ext_id`, `job_id`, `skill_id` |
| `job_posted` | business | 78,769 | `job_id`, `company_id`, `job_title_short`, `job_title`, `job_location`, `job_via`, `job_schedule_type`, `job_work_from_home`, `search_location`, `job_no_degree_mention`, `job_health_insurance`, `job_country`, `salary_rate`, `salary_year_avg`, `salary_hour_avg` |

## Times set by rule

The catalog start is the first posting, 2022-12-31 06:03:30. A company is created at its first posting (3,476 companies), else at the catalog start (10,527). A skill is created at the catalog start. A skill link is created at its posting's time (36,880 links), else at the catalog start (330,080).

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `job_postings_fact` | 78,769 | 16 | none |
| `job_company` | 14,003 | 5 | none |
| `skills_dim` | 26 | 3 | none |
| `skills_job_dim` | 366,960 | 2 | none |

`expected/queries/` holds the answers of the saved questions (`local168`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

`local168` has no gold SQL and two gold answers, which differ only in how a five-way tie among the cohort's most frequent skill ids breaks. The saved query breaks it by lowest `skill_id` and reproduces `_a` (92,689.2222). It does not join `skills_dim`, because the gold counts orphan skill ids.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build jobpostings             # → $NEORISK_DATA_ROOT/jobpostings/v1/ (default data/datasets/)
uv run dataset verify jobpostings            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
