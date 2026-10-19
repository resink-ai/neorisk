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
uv run datagen run examples/ecommerce --profile legacy --out data/legacy-run
uv run datagen export data/legacy-run --legacy-fraud --out data/fraud
uv run bench run data/fraud --oracle

# five-model comparison report (single self-contained HTML, zh or en)
uv run bench compare data/fraud --out reports/payment-risk-benchmark.html \
    --json reports/payment-risk-benchmark.json --lang zh
```

`datagen run` simulates the e-commerce pack with the `bounty_hunters` overlay (the `legacy`
profile); `datagen export --legacy-fraud` writes it in the benchmark's shape. `events.parquet` is
the benchmark input; `golden.parquet` holds hidden golden features and labels' ground truth;
`meta.json` records the seed, the source run (pack, revision, overlay parameters) and the
achieved bad rate. The first run compiles the pack's engine module (45-90 min cold, cached
afterwards).

`bench compare` trains Logistic Regression, Random Forest, XGBoost and two MLPs (`32-16` and
`256-128-64`) on observable point-in-time features built from `events.parquet` only (it never
reads `golden.parquet`), then reports ROC/PR curves, metrics, calibration and per-model SHAP.
On 500k events it runs in a few minutes; the slowest stage is exact TreeSHAP on the Random
Forest (tune with `--shap-rows`; ANN KernelSHAP is a few seconds, tune with `--ann-shap-rows`).
The report ranks models on ranking metrics; log loss/Brier/calibration are flagged as not
comparable between class-weighted and unweighted models. See [`apps/bench/README.md`](apps/bench/README.md) for the feature list and
how to read the report. `data/` and `reports/` are git-ignored.

Note: `--oracle` trains XGBoost on the raw numeric columns plus all golden columns except
`score` (which stays in `golden.parquet` but is not trained on). The golden columns include the
overlay's ground truth (`actor_role`, `invitee_is_zombie`), so it is a ceiling, not a realistic
"best feature engineering" model.
