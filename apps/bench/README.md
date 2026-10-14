# bench

Baseline model benchmark runner for synthetic event datasets.

```
uv run bench run data/fraud [--oracle] [--json out.json]
```

Only `events.parquet` (and `meta.json`) is read unless `--oracle` is passed, in which case
`golden.parquet` is also joined in to train an upper-bound model.
