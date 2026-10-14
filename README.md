# neorisk

Python monorepo managed with [uv](https://docs.astral.sh/uv/) workspaces.

```
libs/   shared libraries   (each has its own pyproject.toml)
apps/   applications       (depend on libs via `workspace = true`)
```

Apps consume libs from the local workspace — no PyPI involved.

## Common tasks

```sh
uv sync                              # install everything into the root .venv
uv run --package hello hello         # run an app
uv run pytest                        # run all tests
uv run ruff check . && uv run ruff format .

uv init --lib libs/<name> --name neorisk-<name>   # new shared library
uv init --app apps/<name> --name <name>           # new application
cd apps/<app> && uv add --workspace neorisk-<name> # app depends on a lib
```

## Synthetic event data + benchmark

```sh
uv run datagen generate --scenario fraud --n-events 100000 --seed 42 --out data/fraud
uv run bench run data/fraud --oracle

# five-model comparison report (single self-contained HTML, zh or en)
uv run bench compare data/fraud --out reports/payment-risk-benchmark.html \
    --json reports/payment-risk-benchmark.json --lang zh
```

`events.parquet` is the benchmark input; `golden.parquet` holds hidden golden features and
labels' ground truth; `meta.json` records seed, config and achieved bad rate.

`bench compare` trains Logistic Regression, Random Forest, XGBoost and two MLPs (`32-16` and
`256-128-64`) on observable point-in-time features built from `events.parquet` only (it never
reads `golden.parquet`), then reports ROC/PR curves, metrics, calibration and per-model SHAP.
On 500k events it runs in minutes; SHAP for the ANNs is the slowest stage (tune with
`--ann-shap-rows`). See [`apps/bench/README.md`](apps/bench/README.md) for the feature list and
how to read the report. `data/` and `reports/` are git-ignored.

Note: `--oracle` trains XGBoost on the raw numeric columns plus all golden columns except
`score` (the label-generating probability, which stays in `golden.parquet` but is not trained
on). It is therefore a golden-feature ceiling, not a realistic "best feature engineering" model.
