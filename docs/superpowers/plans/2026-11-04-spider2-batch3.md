# Spider2 validation datasets, batch 3: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Spider 2.0-lite SQLite catalog not yet covered becomes a validation dataset. There are 30 new datasets. For each one, `uv run dataset build <name>` then `uv run dataset verify <name>` exits 0: every source table rebuilds exactly from the event log, and every saved question agrees.

**Architecture:**
- Each dataset is one `datasets/<name>/` folder laid out like `datasets/sakila/`, with one `apps/dataset/tests/test_dataset_<name>.py` beside it.
  - `dataset.toml`
  - `CONTEXT.md`
  - `specs/pack.py`
  - `specs/source.toml`
  - `specs/ingest.sql`
  - `specs/build.sql`
  - `specs/queries/*.sql`
- Four shared changes come first (Tasks 1–4).
- After them, the dataset tasks share no files, so they can run in parallel.
- `datasets/README.md` is written once, last (Task 35).

**Tech Stack:** Python 3.12, sqlite3, DuckDB, Polars, pyarrow, `neorisk_simkit`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-validation-datasets-design.md`, the dataset contract. The research brief is `docs/research/spider2/BRIEF-batch3.md`. Each dataset's design is in its research report, `docs/research/spider2/<report>.md`: sections 2 (event catalogue), 3 (rebuild rules) and 6 (simkit mapping). The scripts behind each report are in `docs/research/spider2/scripts/<report>/`.

## Global Constraints

- The contract is PR 1's, unchanged:
  - the input is one ordered log with JSON payloads;
  - an entity row is an `<entity>_created` event;
  - `results/` holds every source table, rebuilt exactly;
  - `build.sql` reads only the log views.
- **Exactness** is the comparator's:
  - rows compare as multisets, numbers by value and text byte for byte;
  - NULL, `''` and `'\N'` are three different values;
  - float64 columns get a relative tolerance of 1e-9.
- **Columns holding text together with numbers** are declared in `dataset.toml` `[results.mixed]`.
- **Sources are opened read-only.** Nothing derived from the data goes into git.
- **Time:** source wall clock is stored as if it were UTC.
  - Every time the source lacks comes from the rule its report states.
  - `CONTEXT.md` restates that rule under "Times set by rule".
- **Every block in `ingest.sql` ends in an ORDER BY.**
- **Values:** money that is exact cents is `amount()`. A REAL on a decimal grid is rebuilt from an integer of stated units, never by float arithmetic whose order could change.
- **Query files:** each one's header comment names the Spider2 instance id and says which gold variant it reproduces. Where the report could not reproduce any variant, the query is written from the question text and says so.
- **Rows injected by Spider2** are duplicate prefix rows in every non-pizza `modern_data` table. They come back from an explicit `source_row_duplicated` event, never by dropping them.
- **Out of scope:**
  - no change to the batch-1 and batch-2 datasets;
  - no change to `libs/simkit` beyond what Tasks 1–4 state.
- Code style follows `apps/dataset` and `apps/refdata`, and `ruff check` must be clean.

## Review Focus

1. **Generated columns** (f1 `drivers.full_name`, `lap_times.seconds`, `pit_stops.seconds`):
   - they are part of the source table, so they must appear in `results/`;
   - they must never be inserted, since SQLite computes them from the source DDL.

   Owner: Task 1.
2. **Saved questions that read SQLite views** (stacking, oracle_sql, EU_soccer): the views must exist on the rebuilt side, or the question fails as "no such table". Owner: Task 2.
3. **Float ids above 2⁵³** (switrs `case_id`) and bit-exact float ties (stacking scores):
   - a JSON round trip through DuckDB must keep every bit;
   - an id must never be re-parsed from `entity_key` text.

   Owners: Tasks 13 and 32.
4. **Events with no owner value** (freshsegments' 1,194 month-less rows, and jobpostings' orphaned ids): use a sentinel owner column or raw `i64` ids, never a ref that cannot resolve. Owners: Tasks 8 and 9.
5. **Huge text payloads** (eusoccer's 269 M characters of XML, wwe's 59 MB of HTML):
   - the text must come back byte-exact;
   - build plus verify must finish within 10 minutes;
   - `part_rows` may be lowered for these logs.

   Owners: Tasks 12 and 14.

---

## Shared changes (do these first, in order)

### Task 1: Generated columns in results

**Files:**
- Modify: `apps/dataset/src/dataset/tables.py`
- Modify: `apps/refdata/src/refdata/rebuild.py` (`fill_table`)
- Modify: `apps/dataset/src/dataset/spider2.py` (`_results`, `verify`)
- Test: `apps/dataset/tests/test_tables.py`, `apps/dataset/tests/test_spider2.py`

**Interfaces:**
- Produces: `tables.generated(con, table) -> set[str]`, the columns that `PRAGMA table_xinfo` marks hidden 2 or 3.
- `column_types` and `sqlite_table` include generated columns, in xinfo order.
- `results.json` per table gains `"generated": [...]`.
- `fill_table(..., want, dst)` inserts only the columns of `want` that are not generated.

- [ ] **Step 1:** write `test_generated_column_in_results_not_inserted`.
  - Build a source table `t (a INTEGER, b INTEGER GENERATED ALWAYS AS (a*2) VIRTUAL)`.
  - Assert that `sqlite_table` has columns `["a", "b"]`.
  - Assert that `fill_table` over a block selecting only `a` fills `b` correctly.
- [ ] **Step 2:** run it. It must FAIL.
- [ ] **Step 3:** implement the change.
- [ ] **Step 4:** run it, then `uv run pytest apps/dataset apps/refdata -q`. Everything must PASS.
- [ ] **Step 5:** commit: `feat(dataset): generated columns appear in results and are never inserted`.

### Task 2: Source views replayed for saved questions

**Files:**
- Modify: `apps/dataset/src/dataset/spider2.py`
- Test: `apps/dataset/tests/test_spider2.py`

**Interfaces:**
- `results.json` gains `"views": {name: sql}`, from `sqlite_master` rows of type `view`, in rowid order.
- `verify` creates them in the rebuilt in-memory database after its tables are filled, and before any query runs.
- Views are not results tables, and nothing compares them.

- [ ] **Step 1:** write `test_query_over_a_view_verifies`. The shop fixture gets a view and a query that reads it. Verify must be ok.
- [ ] **Step 2:** run it. It must FAIL with "no such table".
- [ ] **Step 3:** implement the change.
- [ ] **Step 4:** run the dataset tests, then rebuild and verify `sakila` and `oraclesh`. Their views must stay harmless.
- [ ] **Step 5:** commit: `feat(dataset): replay source views before saved questions`.

### Task 3: `dataset context` writes the generated parts of CONTEXT.md

**Files:**
- Create: `apps/dataset/src/dataset/context.py`
- Modify: `apps/dataset/src/dataset/cli.py`
- Test: `apps/dataset/tests/test_dataset_cli.py`

**Interfaces:**
- `uv run dataset context NAME` prints four markdown sections from the built version: the event catalogue table, the expected output table, the questions line and the regenerate block. Each is in the exact shape of `datasets/pizzarunner/CONTEXT.md`.
- It exits 2 when the dataset is not built.
- The prose sections are written by hand.

- [ ] **Step 1:** write `test_context_prints_catalogue_from_build`. Over the `built` shop fixture, assert the event and table rows with their counts.
- [ ] **Step 2:** run it. It must FAIL.
- [ ] **Step 3:** implement it.
- [ ] **Step 4:** run it. It must PASS.
- [ ] **Step 5:** commit: `feat(dataset): context command for CONTEXT.md's generated sections`.

### Task 4: Owner-less and sentinel-owner events (only if needed)

Before writing code, check whether an ingest `-- event` block whose `owner=` column holds a constant sentinel text (e.g. `'none'`) ingests, logs and rebuilds. Use one row of the shop fixture.
- **If it does:** record that as a ruling and write no code.
- **If it does not:** make the smallest change to `apps/refdata/src/refdata/ingest.py` that allows it, under TDD, with `test_sentinel_owner_event`.

Commit (if code): `feat(refdata): events owned by a sentinel value`.

---

## Dataset tasks

Every dataset task has the same steps:

- [ ] **Step 1: Write the test.** Create `apps/dataset/tests/test_dataset_<name>.py` in the shape of `test_dataset_sakila.py`:
  - `COUNTS` holds the per-event-type counts from the report's section 2;
  - the table count is every source table;
  - the query count is every Spider2 question for these tables.
- [ ] **Step 2: Run it and watch it fail.** Run `uv run pytest apps/dataset/tests/test_dataset_<name>.py -q`. Expected: FAIL, because the dataset does not exist.
- [ ] **Step 3: Write `datasets/<name>/`** from the report:
  - `dataset.toml`, with the mixed columns;
  - `specs/source.toml`, `pack.py`, `ingest.sql` and `build.sql`;
  - `specs/queries/<id>.sql`, using gold SQL where the report reproduced it, otherwise the reproduced variant.
- [ ] **Step 4: Make it pass.** Run `uv run dataset build <name>` and `uv run dataset verify <name>` until both exit 0 and the test passes.
  - Where the report's counts were wrong, fix `COUNTS` to the built log only after checking the difference against the report. Record that as a ruling.
- [ ] **Step 5: Write `CONTEXT.md`.**
  - Paste the output of `uv run dataset context <name>`.
  - Write the prose sections in the shape of `datasets/pizzarunner/CONTEXT.md`: what this is, raw data, how the log was made, times set by rule, and extend.
- [ ] **Step 6: Commit.** Message: `feat(datasets): <name> validation dataset, exact round trip`.

| Task | Dataset | Source file (tables) | Report | Notes from research |
|---:|---|---|---|---|
| 5 | `music` | music.sqlite | music.md | Same data as chinook. Copy chinook's pack and ingest, write a build.sql with the PascalCase names. Questions: local244. |
| 6 | `veg` | bank_sales_trading (`veg_*`) | veg.md | `index` rides as `ord` across the sale and return blocks; REALs come back from integer grids. Questions: local284, local285. |
| 7 | `datamart` | bank_sales_trading (`weekly_sales`, `cleaned_weekly_sales`) | datamart.md | `avg_transaction` is rebuilt by integer half-up rounding. Questions: local301, local302. |
| 8 | `freshsegments` | bank_sales_trading (`interest_*`) | freshsegments.md | 1,194 month-less rows: a sentinel owner (Task 4) at rule time N. Questions: local077, local078. |
| 9 | `jobpostings` | city_legislation (job and skills tables) | jobpostings.md | ids are raw `i64`, not refs (90% are orphaned). Questions: as listed in the report. |
| 10 | `legislators` | city_legislation (legislators tables) | legislators.md | `legislation_date_dim` is a generated calendar in build.sql. |
| 11 | `ipl` | IPL | ipl.md | Placeholder entities for team 1 and player 35; the `teams_swapped` flag. Questions: 11. |
| 12 | `eusoccer` | EU_soccer | eusoccer.md | Byte-exact XML; a view (Task 2); tie-sensitive local219 and local283. |
| 13 | `switrs` | California_Traffic_Collision | traffic.md | `case_id` is f64 in every payload. |
| 14 | `wwe` | WWE | wwe.md | Matches rebuild from distinct matches plus 7 scrape runs; byte-exact HTML. |
| 15 | `f1` | f1 | f1.md | 11 derived tables; generated columns (Task 1); 39 override rows for `drives`, carried as events. Within 1e-9 is acceptable for `lap_time_stats` (float64). |
| 16 | `baseball` | Baseball | baseball.md | 91 mixed columns; `inf` and noisy `baopp` travel as text. Record local007 as not reproducible. |
| 17 | `dbimdb` | Db-IMDB | dbimdb.md | `Person` derived in first-seen credit order; re-prove it in DuckDB. |
| 18 | `imdb_movies` | imdb_movies | imdbmovies.md | `date_published` is mixed. |
| 19 | `atliq` | education_business (`hardware_*`) | atliq.md | 4-decimal REALs through integers of 1e-4. |
| 20 | `parchposey` | education_business (`web_*`) | parchposey.md | Money from integer cents; carried ids. |
| 21 | `university` | education_business (`university_*`) | university.md | Grades and GPA as integers of tenths. |
| 22 | `staffhours` | education_business (`StaffHours`) | edu_misc.md | |
| 23 | `salaries_india` | education_business (`SalaryDataset`) | edu_misc.md | The salary text has a lakh formatter, or is carried verbatim if simpler. local253: the reproducible variant. |
| 24 | `aliens` | city_legislation (`alien*`) | aliens.md | `alien_data` is derived; `'Nan'` becomes NULL. |
| 25 | `cities` | city_legislation (`cities*`) | cities.md | Keep the swapped latitude and longitude, and the city_id order. |
| 26 | `unicorns` | modern_data (`companies_*`) | unicorns.md | Duplicate markers. Question: local049. |
| 27 | `nyctrees` | modern_data (`trees`, `income_trees`) | trees.md | Duplicate markers. Questions: local040, local041. |
| 28 | `covidstates` | modern_data (`statistics`) | modern_misc.md | Duplicate markers; no questions. |
| 29 | `wordlist` | modern_data (`word_list`) | modern_misc.md | The 2 NULL words stay NULL; duplicate markers. Question: local201. |
| 30 | `oraclesql` | oracle_sql (all 38) | oraclesql.md | 11 views (Task 2); `locations` is derived; 5 empty tables. |
| 31 | `bowling` | BowlingLeague | bowling.md | The stats cut-off date is a constant in build.sql. |
| 32 | `stacking` | stacking | stacking.md | 3 views (Task 2); bit-exact scores. Questions: local262–264. |
| 33 | `entertainment` | EntertainmentAgency | entertainment.md | `ztbl*` tables are generated in build.sql. |
| 34 | `school` | school_scheduling | school.md | StudGPA is a snapshot. |

### Task 35: Catalogue and docs

- Add the 30 rows to `datasets/README.md` from each built manifest.
- Add a batch-3 row block to `apps/refdata/README.md`'s table.
- Add a "Batch 3" section to the validation-datasets design, listing the datasets and each one's event shape (natural, partly imposed, mostly imposed).
- Commit the research reports and scripts in their own commit: `docs(research): Spider2 batch-3 reverse-engineering reports`.
- Run the full suite and `ruff check`.
