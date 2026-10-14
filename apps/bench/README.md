# bench

Baseline model benchmark runner for synthetic event datasets.

```
uv run bench run data/fraud [--oracle] [--json out.json]
```

Only `events.parquet` (and `meta.json`) is read unless `--oracle` is passed, in which case
`golden.parquet` is also joined in to train an upper-bound model.

## About `--oracle`

`--oracle` trains XGBoost on the raw numeric columns plus all golden columns **except `score`**
(the probability the labels were sampled from; it stays in `golden.parquet` but is not a
feature). The resulting model is a golden-feature ceiling, not a realistic upper bound for
engineered features.
