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
  `invitee_is_zombie`, `score`). Graph features on a transaction are looked up as-of from the
  user's invite row (frozen at invite time).
- `meta.json` - seed, scenario, config, achieved bad rate

## Adding a scenario

1. Create `src/datagen/scenarios/<name>.py` exposing `generate(cfg) -> Dataset`
   (use `neorisk_simkit` primitives; keep entities as integer `idx` and let `export` attach UUIDs).
2. Register it in `datagen.scenarios.SCENARIOS`: `{"fraud": fraud.generate, "<name>": <name>.generate}`.
3. Add tests with a unique file basename.
