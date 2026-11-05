# stacking

## What this is

The results store of one person's automated model-stacking tool, run over 20 Kaggle tasks: each run (problem, version) profiles its features, scores a pool of level-0 models and a level-1 Stack over 3 steps, and weights the models and features at each step.

Version `v1`, kind `spider2`. The input is one ordered event log of 10,297 events; the output is the 7 source tables, rebuilt exactly, and the answers to 3 saved Spider 2.0 questions.

## Raw data

`stacking.sqlite` (all 7 tables, and 3 views: `stack_ok`, `solution_ext`, `stack_ok_score`). Real experiment output; the author is unidentified and the licence is unstated. None of the Kaggle data itself is in the file.

There are no times in the source. The order is real: `solution` lists the 101 runs in insertion order, and every child table holds each run's rows in that same order, contiguous, steps ascending. Every time is a rule.

Scores and importances are NUMERIC and decide the saved questions by float equality (47 soft ties between the Stack and the best base model), so they travel as f64 and come back bit-exact. Integer scores (exactly 0 or 1) come back as 1.0, which the NUMERIC affinity stores as the integer again. `eda.range` is declared BLOB but holds text, carried byte-exact.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/stacking.md`](../../docs/research/spider2/stacking.md).

## How the log was made

Problems and runs are entities: a run (`solutions`) refers to its problem and holds its config, and is created by a `run_configured` event. Every other row is an event owned by its run: an eda row is `feature_profiled`, a model_score row `model_scored`, a model_importance row `model_weighted`, a feature_importance row `feature_weighted`, and a model row `step_completed`, which marks the end of a step and carries its L1_model. Each event keeps its source rowid as `src_rowid` and `ord`. Models and features are text labels, not entities. The 3 views produce no events: `dataset verify` replays their stored SQL over the rebuilt tables before the saved questions run.

`uv run dataset build stacking` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `problems_created` | entity | 20 | `problem_key`, `ext_id`, `path`, `type`, `target` |
| `run_configured` | entity | 101 | `run_key`, `ext_id`, `problem`, `version`, `correlation`, `nb_model`, `nb_feature`, `score`, `test_size`, `resampling` |
| `feature_profiled` | business | 1,547 | `run`, `src_rowid`, `feature`, `type`, `range`, `drop_user`, `drop_correlation`, `target` |
| `model_scored` | business | 2,872 | `run`, `src_rowid`, `step`, `model`, `train_score`, `test_score` |
| `model_weighted` | business | 2,567 | `run`, `src_rowid`, `step`, `model`, `importance` |
| `feature_weighted` | business | 2,887 | `run`, `src_rowid`, `step`, `feature`, `importance` |
| `step_completed` | business | 303 | `run`, `src_rowid`, `step`, `L1_model` |

## Times set by rule

All of them. Run k, the k-th `solution` rowid, starts at 2023-01-01 00:00:00 + k hours (the anchor is arbitrary; PSS3E5 is an early-2023 Kaggle episode). Its run entity and eda rows are at the start. Its step-s rows are at + s minutes, then + 0, 1, 2 and 3 seconds for scores, model weights, feature weights and the step's completion. A problem is created at its first run's time. Only the order is data; the spacing is not. There are no snapshot events, so there is no snapshot time N.

## Snapshot columns

None: every entity attribute travels in its creation event.

| Column | Verdict | Reason |
|---|---|---|
| `problems.ext_id` | creation | The source key (`name`). |
| `problems.path` | creation | Part of the problem's definition, the data it was set up on; the source shows no change. |
| `problems.type` | creation | The original type (classification or regression). |
| `problems.target` | creation | Part of the problem's definition, the column it predicts. |
| `solutions.ext_id` | creation | The source key (`name`, `version`). |
| `solutions.problem` | creation | An immutable ref: the problem the run is of. |
| `solutions.version` | creation | Part of the run's key. |
| `solutions.correlation` | creation | Run config, set before the run (0.75 in all 101). |
| `solutions.nb_model` | creation | Run config: the pool size the run is set to keep after step 1. |
| `solutions.nb_feature` | creation | Run config: the feature count the run is set to keep at step 3. |
| `solutions.score` | creation | Run config: a score threshold set before the run (0.7 in 69), not a result. |
| `solutions.test_size` | creation | Run config, set before the run. |
| `solutions.resampling` | creation | Run config, set before the run. |

No column qualifies: a `solution` row is the run's configuration, written before any step, and changes between runs make a new version, not an update. Every result (scores, importances, the L1 model) already travels on its own event. The run's creation event is `run_configured`, the name the research gives it: configuring is the act the row records. Problems keep `problems_created`; they are created at their first run's time by rule.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `problem` | 20 | 4 | none |
| `solution` | 101 | 8 | none |
| `eda` | 1,547 | 8 | none |
| `model` | 303 | 4 | none |
| `model_score` | 2,872 | 6 | none |
| `model_importance` | 2,567 | 5 | none |
| `feature_importance` | 2,887 | 5 | none |

`expected/queries/` holds the answers of the saved questions (`local262`, `local263`, `local264`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, replays the source views, and compares the tables and the answers exactly: rows as multisets, numbers by value, text byte for byte.

Every float column is declared in `dataset.toml` `[results.exact]`, so it compares bit for bit instead of within the usual relative 1e-9: every answer turns on exact ties between scores.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build stacking             # → $NEORISK_DATA_ROOT/stacking/v1/ (default data/datasets/)
uv run dataset verify stacking            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table and view names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly, scores to the bit.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
