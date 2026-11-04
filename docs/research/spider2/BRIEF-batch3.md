# Research brief: Spider2 validation datasets, batch 3

Your job is to reverse-engineer one or more Spider 2.0-lite SQLite catalogs into the **event log** that regenerates their tables. A catalog is a whole file, or one coherent group of tables inside a file. The work is analysis only. You write one report per catalog, plus the scripts behind its numbers, and nothing else.

Batch 3 covers every Spider2 SQLite catalog that batches 1 and 2 did not. Several of these catalogs are reference data or pre-aggregated data, not natural event streams. The project's principle still holds: **everything comes from the log**. Your report must say, measured, how each table becomes events and whether that is natural or imposed by a rule.

## Background (read these first)

- **`docs/superpowers/specs/2026-11-03-validation-datasets-design.md`** sets the dataset contract. Read "The dataset contract", "The log" and "Entities as events":
  - one ordered log of JSON-payload events;
  - lookup rows are entities, and each becomes an `<entity>_created` event at its creation time;
  - `results/` holds every source table, rebuilt exactly.
- **`apps/refdata/README.md`** covers the conventions:
  - **Time:** source wall clock is stored as UTC.
  - **Entity keys:** the 1-based rank of `ext_id`.
  - **Refs:** a ref is given as the source id.
  - **Order:** events sort by `ord`.
  - **Exactness:** tables compare as multisets of rows. INTEGER and REAL compare by value, text byte-exact. NULL, `''` and `'\N'` are three different values.
- **`docs/research/spider2/northwind.md` and `olist.md`** are two finished reports. Match their section structure and density.
- **`datasets/sakila/specs/` and `datasets/weblog/specs/`** show what a finished dataset looks like: `pack.py`, `source.toml`, `ingest.sql`, `build.sql` and `queries/`.
- **simkit pack API:** `libs/simkit`.
  - Column types are `ref`, `amount`, `cat`, `opt`, `ts`, `text`, `f64`, `i64` and `i32`.
  - An entity gets a key and `created_at`.
  - An event gets `event_id`, `event_type`, `event_time`, `seq`, `partition_id`, `cause_id` and `action_id`.

## Rules

- **Open the data read-only.** Use `sqlite3 -readonly data/spider2/<file>.sqlite`, or Python with `python3 -I` and `mode=ro` URIs. Never write to `data/`.
- **Spider2 questions** are in `data/spider2-meta/spider2-lite.jsonl` (field `db`).
  - Gold SQL, where it exists, is at `https://raw.githubusercontent.com/xlang-ai/Spider2/main/spider2-lite/evaluation_suite/gold/sql/<instance_id>.sql`.
  - Gold CSVs are under `.../gold/exec_result/`.
  - Often neither exists.
- **Write only these two things:**
  - `docs/research/spider2/<report>.md`
  - `docs/research/spider2/scripts/<report>/`

  Do not touch any other file. Do not run git commands that change state: no add, commit, stash, checkout or branch.
- **Every number in the report comes from a script you saved.** Name the script next to the number. Save each raw output next to its script as `out_<script>.txt`.
- Be concrete and measured, not speculative. Put anything you are unsure about under Open questions.

## How to treat tables that are not event-shaped

| Table shape | Treat it as |
|---|---|
| A log or transaction table (a row per thing that happened, with a time) | Business events, one per row or per lifecycle step |
| A lookup or master table (players, teams, products) | Entities. Give `created_at` from a real column if one exists, otherwise from a stated rule: the first event that uses it, or the catalog's start. |
| An attribute snapshot table (one row per entity per date) | Update events (`<entity>_rated`, `price_changed`, ...) at that date |
| A pre-aggregated fact (weekly sales, monthly totals) | One reported event per row (`weekly_sales_reported`) at its period's date. Say so plainly: no finer grain exists. |
| A table that is a pure function of other tables (cleaned copies, `_ext` tables, stats, ranks) | Derived. Prove it with a query (0 differing rows) and give the SQL that rebuilds it in `build.sql`. It produces no events. |
| A static table with no time and no use (word lists, calendar helpers like `ztblDays`) | An entity at a rule time, or derived when it is generated (a calendar). Say which, and why. |
| An exact or near copy of a catalog already done (`chinook`, `sakila`, `olist`, ...) | Measure the equivalence. Propose reusing that dataset's events with a different `build.sql`, or folding the questions into it. |

## Report sections

0. **What this catalog is:**
   - origin, with the evidence for it;
   - row counts;
   - licence ("unstated" is fine);
   - whether the data is real, anonymised, generated or course data.

   0.1. **How Spider 2.0 uses it:** a table of every question for this catalog's tables: instance id, what it asks, and whether gold SQL is present. Reproduce 2 to 4 gold answers where you can.
1. **Inventory, keys, joins:** primary keys, foreign keys and orphans, all measured. Mark the tables that are copies of one another or derived.
2. **Event catalogue:** the proposed events and entities.
   - For each: its owner, its time column, its attributes, which source rows it comes from, and the count you expect.
   - Say whether each event's time is natural or set by a rule.
   - Explain what is **not** an entity, and why.
3. **Rebuild rules and blockers to an exact round trip:**
   - derived columns: are they exact functions of other rows? Prove it.
   - the text formats of times and numbers: trailing zeros, time-zone suffixes, `'\N'`;
   - floats, duplicates, and rows that have no time.

   Times the source lacks must come from a stated rule.
4. **Measured quirks:** dirty rows, nulls, out-of-order times, duplicates and generator fingerprints.
5. **Distributions to fit** (for stage 2): arrivals, inter-event gaps, amounts, categorical mixes and lifecycle conversion rates.
6. **simkit mapping sketch:**
   - the pack's entities and events, with column types;
   - the ingest `ORDER BY`, `owner` and `ord` choices;
   - the `build.sql` approach for each table.
7. **Open questions and risks.**

End each report with a 5-line summary:
- whether an exact round trip is feasible (yes, no, or with caveats);
- the proposed dataset name or names (lowercase, `[a-z0-9_]`);
- the number of event types and the number of entities;
- how event-shaped the catalog really is (natural, partly imposed, mostly imposed);
- the hardest blocker.
