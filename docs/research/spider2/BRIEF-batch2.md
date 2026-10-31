# Research brief: Spider2 reference datasets, batch 2

You are reverse-engineering one Spider 2.0-lite SQLite catalog (or one coherent table group inside it) into the **event log** that would regenerate its tables. This is analysis only: you write one report plus the scripts behind its numbers, and nothing else.

## Background (read these first)

- `apps/refdata/README.md`: the stage-1 pipeline and its conventions. A project's `specs/ingest.sql` turns source tables into simkit events/entities; `specs/views.sql` (DuckDB over the Parquet output) rebuilds every source table. The round trip must be **exact**: every source table equals the rebuilt one as a multiset of rows, byte-exact text, with INTEGER and REAL compared by value, and NULL, `''` and `'\N'` kept distinct.
- `docs/superpowers/specs/2026-10-30-spider2-reference-datasets-design.md`: the design and the per-dataset decisions of batch 1.
- `docs/research/spider2/bank_clicklog.md` and `olist.md`: two finished reports. **Match their section structure and density.**
- `examples/olist/specs/` and `examples/databank/specs/`: what a finished project looks like (pack.py, source.toml, ingest.sql, views.sql, queries/).
- simkit pack API: `packages/neorisk_simkit` (column types `ref`, `amount`, `cat`, `opt`, `ts`, `text`, `f64`, `i64`; entities get key + `created_at`; events get event_id, event_type, event_time, seq, partition_id, cause_id, action_id).

## Rules

- **Open the data read-only:** `sqlite3 -readonly data/spider2/<file>.sqlite`, or Python with `python3 -I` and `mode=ro` URIs. Never write to `data/spider2/`.
- **Spider2 questions** are in `data/spider2-meta/spider2-lite.jsonl` (field `db`). Gold SQL, where it exists, is at `https://raw.githubusercontent.com/xlang-ai/Spider2/main/spider2-lite/evaluation_suite/gold/sql/<instance_id>.sql`; often it does not exist.
- **Write only:**
  - `docs/research/spider2/<name>.md`
  - `docs/research/spider2/scripts/<name>/`

  Do not touch any other file, and do not run git commands that change state (no add, commit, stash or checkout).
- **Every number in the report comes from a script you saved.** Name the script next to the number.
- Be concrete and measured, not speculative. Where you are unsure, put it under Open questions.

## Report sections (same as batch 1)

0. **What this catalog is:** origin and evidence, row counts, licence (state what you can find; "unstated" is fine). Is it real, anonymised, generated or course data?
0.1 **How Spider 2.0 uses it:** a table with every question for this db (id, analysis, gold SQL present?). Reproduce 2–4 gold answers where feasible.
1. **Inventory, keys, joins:** primary keys, foreign keys and orphans, measured.
2. **Event catalog:** the proposed events and entities. For each: owner, time column, attributes, which source rows it comes from, and the count you expect. Tables that are already logs stay logs. Lookup tables become entities. Explain what is **not** an entity and why.
3. **Rebuild rules and blockers to an exact round trip:** derived columns (are they exact functions of other rows? prove it), text formats of times and numbers (trailing zeros, time-zone suffixes, `'\N'`), floats, duplicates, rows that have no time. Times the source lacks must come from a stated **rule**, capped at the snapshot time.
4. **Measured quirks:** dirty rows, nulls, out-of-order times, duplicates, generator fingerprints.
5. **Distributions to fit** (for stage 2): arrivals, inter-event gaps, amounts, categorical mixes, lifecycle conversion rates.
6. **simkit mapping sketch:** pack entities/events with column types; ingest `ORDER BY` and owner/ord choices.
7. **Open questions and risks.**

End with a 5-line summary: feasible for an exact round trip (yes/no/with caveats), proposed project name(s), events count, entities count, and the hardest blocker.
