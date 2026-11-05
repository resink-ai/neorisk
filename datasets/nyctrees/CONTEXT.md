# nyctrees

## What this is

The 2015 NYC Street Tree Census, one row per street tree (species, size, status, health, address and location), with a per-ZIP household-income lookup.

Version `v1`, kind `spider2`. The input is one ordered event log of 1,374,766 events; the output is the 2 source tables, rebuilt exactly, and the answers to 2 saved Spider 2.0 questions.

## Raw data

`modern_data.sqlite` (the tables `trees` and `income_trees`). Real data: the NYC Parks tree census from NYC Open Data, and American Community Survey household-income estimates for 216 NYC ZIPs (vintage unknown). Licence unstated in Spider2.

`trees` has 690,626 rows for 683,788 trees; `idx` is a pandas index. Rows 1–6,838 are copies Spider2 injected (1% of the trees), each identical to a row further down. `income_trees` has 220 rows for 216 ZIPs: rows 1–2 are injected copies, and ZIPs 10463 and 11370 appear twice with identical values inside the base. Neither table has any time column; the census's own survey dates are not in this copy.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/trees.md`](../../docs/research/spider2/trees.md).

## How the log was made

Each tree is an entity, created with its fixed traits: `idx`, species, address, ZIP, borough, NTA and coordinates. What the surveyor saw (`tree_dbh`, `stump_diam`, `status`, `health`) is a `trees_snapshot` event owned by the tree, in `idx` order. The 132 species are an entity keyed by `spc_latin`; a tree's species is a ref, NULL on 31,938 rows. Each ZIP's six income figures are a `zip_incomes` entity. ZIP is a plain integer on the tree, not a ref: 6 tree ZIPs (Central Park's 83 among them) have no income row. `borocode` and `state` are not carried: `specs/build.sql` derives borocode from boroname (Manhattan 1 to Staten Island 5) and writes `state` as the constant 'New York'.

Of each set of identical rows, the last by rowid is the entity, and every earlier copy is one `source_row_duplicated` event naming its table, its tree id or ZIP and its source rowid: 6,838 for `trees`, 4 for `income_trees`. `specs/build.sql` adds one more copy of the row for each. Three of the four reproduced gold answers count these copies, so they are kept, not dropped.

`uv run dataset build nyctrees` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant; snapshots follow `idx`, duplicate markers their source rowid. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `species_created` | entity | 132 | `species_key`, `ext_id`, `spc_common` |
| `trees_created` | entity | 683,788 | `tree_key`, `ext_id`, `idx`, `species`, `address`, `zipcode`, `boroname`, `nta_name`, `latitude`, `longitude` |
| `zip_incomes_created` | entity | 216 | `zip_key`, `ext_id`, `estimate_total`, `moe_total`, `estimate_median_income`, `moe_median_income`, `estimate_mean_income`, `moe_mean_income` |
| `trees_snapshot` | business | 683,788 | `tree_id`, `tree_dbh`, `stump_diam`, `status`, `health` |
| `source_row_duplicated` | business | 6,842 | `source_table`, `ext_id`, `src_rowid` |

## Times set by rule

Every time is a rule, since the source has none. Trees, species and ZIP incomes are created at T0, and snapshots and duplicate markers happen at N, with T0 = N = 2015-01-01 00:00:00 UTC (the census ran in 2015–2016). No order of events in this log is data.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `trees` | 690,626 | 16 | none |
| `income_trees` | 220 | 7 | none |

`expected/queries/` holds the answers of the saved questions (`local040`, `local041`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

Neither question has gold SQL; both are written from the question. `local040` reproduces gold CSV `_c` (raw trees joined to distinct income rows: Queens 252,846, Brooklyn 177,132, Staten Island 106,374). `local041` returns both gold readings in one row: `_a` 78.147266 over raw rows, and `_b` 82.649376 over distinct trees with a health value.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build nyctrees             # → $NEORISK_DATA_ROOT/nyctrees/v1/ (default data/datasets/)
uv run dataset verify nyctrees            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
