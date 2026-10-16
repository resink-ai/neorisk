# datagen

Synthetic tabular event data generator (fraud scenario first).

```bash
uv run datagen generate --scenario fraud --n-events 100000 --seed 42 --out data/fraud
```

## Flags

| Flag | Default | Meaning |
|---|---|---|
| `--scenario` | required | scenario name (`fraud`) |
| `--n-events` | `FraudConfig.n_events` | number of events |
| `--seed` | 0 | RNG seed; same seed gives identical output |
| `--span-days` | `FraudConfig.span_days` | time span of the data |
| `--bad-rate` | `FraudConfig.target_bad_rate` | calibrated target label rate |
| `--out` | required | output directory |

## Outputs

- `events.parquet` - raw event and entity columns plus `label` (benchmark input; no golden features)
- `golden.parquet` - `event_id` + hidden golden features + `score`
  (`u_amt_{count,sum,mean,max,min}_{7,14,30}d`, `dev_users_n_unique_7d`, `addr_chg_sum_30d`,
  `amt_ratio_30d`, `inv_bonus_{count,sum,mean,max}_{7,14,30}d`, `inv_zombie_mean_30d`,
  `invr_bonus_{count,sum,mean,max}_{7,14,30}d`, `invr_zombie_mean_30d`, `invitee_is_zombie`,
  `score`).
  - `inv_*` (invitee side): the inviter's invite activity at the invite row that brought the
    event's user in, carried as-of to the user's later events, i.e. frozen at invite time.
  - `invr_*` (inviter side): the event's user's own invites in [t-w, t), evaluated at every
    event of that user, so bounty hunters' own transactions carry them.
  - zombie ratios use the latent zombie flag, which is not exported in `events.parquet`.
- `meta.json` - seed, scenario, config, achieved bad rate

## Adding a scenario

1. Create `src/datagen/scenarios/<name>.py` exposing `generate(cfg) -> Dataset`
   (use `neorisk_simkit` primitives; keep entities as integer `idx` and let `export` attach UUIDs).
2. Register it in `datagen.scenarios.SCENARIOS`: `{"fraud": fraud.generate, "<name>": <name>.generate}`.
3. Add tests with a unique file basename.

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
