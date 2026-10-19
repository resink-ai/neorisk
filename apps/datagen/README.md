# datagen

Command line of the agentic event simulator (`neorisk_simkit`): validate and run a project
folder (a pack, its profiles and overlays), check a run, replay or export it.

```bash
uv run datagen validate PROJECT [--profile P] [--set K=V]... [--overlay N]... [--no-overlays]
uv run datagen run PROJECT [--profile P] [--set K=V]... [--seed N] [--out DIR] [--force]
uv run datagen check PROJECT [--profile P] [--run-dir DIR] [--baseline DIR] [--out DIR]
uv run datagen export RUN_DIR --legacy-fraud --out DIR
uv run datagen schema TARGET [--format sql|json] [--dialect postgres|duckdb]
uv run datagen replay DATASET [--sink URI]...
uv run datagen benchmark WORKLOAD [--cold] [--out REPORT.json]
```

The `generate` subcommand (the hand-coded fraud scenario) was retired in M3 (D89): it prints
the replacement commands below and exits 2.

## Fraud benchmark data: `export --legacy-fraud`

```bash
uv run datagen run examples/ecommerce --profile legacy --out data/legacy-run
uv run datagen export data/legacy-run --legacy-fraud --out data/fraud
```

The `legacy` profile runs the e-commerce pack with the `bounty_hunters` overlay. `export
--legacy-fraud` writes the run in the shape `bench` reads (D87):

- `events.parquet` - `order_placed` rows (`event_type` 0) and the inviter's
  `referral_bonus_paid` rows (`event_type` 1, `user_id` = the invitee, `inviter_id` = the
  inviter), user/device/product attributes as integer codes as of the event time, and `label`
  (the row's user, or the inviter on invite rows, is a labeled ring member).
- `golden.parquet` - `event_id` + hidden golden features over strictly earlier rows
  (`u_amt_{count,sum,mean,max,min}_{7,14,30}d`, `dev_users_n_unique_7d`, `amt_ratio_30d`,
  `inv_bonus_{count,sum,mean,max}_{7,14,30}d`, `invr_bonus_{count,sum,mean,max}_{7,14,30}d`)
  and the overlay's ground truth (`invitee_is_zombie`, `actor_role`, `score` = `label`).
  - `inv_*` (invitee side): the inviter's invite activity at the invite row that brought the
    event's user in, carried as-of to the user's later events.
  - `invr_*` (inviter side): the event's user's own invites in [t-w, t), at every event of that
    user, so bounty hunters' own orders carry them.
- `meta.json` - scenario (`ecommerce+bounty_hunters`), seed, `source` (pack, revision, overlay
  parameters, run name), `feature_allowlist`, `golden_columns`, achieved bad rate.

Exit 2 without `--legacy-fraud`, without `--out`, or when `RUN_DIR` has no `manifest.json`.

## Project folders: `validate` and `run`

```bash
uv run datagen validate examples/ecommerce_s1 [--profile sample] [--set K=V]...
uv run datagen run examples/ecommerce_s1 [--profile sample] [--set K=V]... \
    [--seed N] [--threads N] [--out DIR] [--force] [--checked]
```

`validate` prints the pack, partitions, events, processes, warnings and the memory caps table
(hard cap and estimate in MiB), then `OK` or the errors. `run` writes
`<project>/<paths.out>/<profile>-s<seed>` (or `--out`) and prints rows per table, rounds and
seconds. `--force` replaces an existing folder; the old one is deleted only after the new one is
in place. Exit codes: 0 ok, 2 validation/usage error or folder exists, 3 a hard memory cap was
hit (the item is named on stderr).

## Replay: `datagen replay`

```bash
uv run datagen replay DATASET [--first N | --last N] [--from T] [--to T] [--types a,b] \
    [--sink URI]... [--numbers] [--batch-rows N] [--preset NAME]
```

Reads a dataset's Parquet (never reruns the simulation) in canonical order and tees every batch
to each sink. `T` is RFC 3339 or a date (`2026-03-01`); `--from` is inclusive, `--to` exclusive.
Sinks: `stdout[:?format=jsonl|table|csv]` (default `stdout`, jsonl; a closed pipe ends the
replay without error) and `file:PATH[?format=jsonl|json-array|csv|parquet]` (format defaults from
the extension: `.jsonl`, `.json` = json-array, `.csv`, `.parquet`). A file is written to
`PATH.tmp` and renamed when complete; a sink that fails midway leaves no file and no `.tmp`.
`kafka://` arrives in M4. IDs and amounts are JSON strings unless `--numbers`. An empty selection
exits 0 with zero rows (`json-array` writes `[]`).

Presets come from `[replay.presets.<name>]` in the project's `datagen.toml`
(`DATASET/../../datagen.toml`; keys `first last from to types sink numbers batch_rows`);
explicit flags override preset keys. The report goes to stderr: per sink rows, rate, first/last
canonical key and error. Exit codes: 0 ok, 1 a sink failed, 2 bad arguments or unavailable sink.
