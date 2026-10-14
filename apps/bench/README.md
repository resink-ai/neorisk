# bench

Baseline model benchmark runner for synthetic event datasets.

```
uv run bench run data/fraud [--oracle] [--json out.json]
```

Only `events.parquet` (and `meta.json`) is read unless `--oracle` is passed, in which case
`golden.parquet` is also joined in to train an upper-bound model. Raw baselines never see
golden columns (including the graph features `inv_*` / `invr_*`): loading fails if any column
listed in `meta.json["golden_columns"]` appears in `events.parquet`.

The split is chronological (60/20/20, ties broken by `event_id`). Raw features are the numeric
non-`*_id` columns with NaN/null filled with -1. If the training split has a single class,
each model still reports NaN metric rows for `valid` and `test`.

## About `--oracle`

`--oracle` trains XGBoost on the raw numeric columns plus all golden columns **except `score`**
(the probability the labels were sampled from; it stays in `golden.parquet` but is not a
feature). The resulting model is a golden-feature ceiling, not a realistic upper bound for
engineered features.
