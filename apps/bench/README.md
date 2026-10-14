# bench

Baseline model benchmark runner for synthetic event datasets.

```
uv run bench run data/fraud [--oracle] [--json out.json]
```

Only `events.parquet` (and `meta.json`) is read unless `--oracle` is passed, in which case
`golden.parquet` is also joined in to train an upper-bound model.

## About `--oracle`

`--oracle` trains XGBoost on the raw numeric columns plus ALL golden columns, **including `score`**,
which is the probability the labels were sampled from. The resulting model is a Bayes ceiling
(close to the best achievable AUC), not a realistic upper bound for engineered features.
