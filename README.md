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
uv run datagen run examples/ecommerce --profile bench --overlay bounty_hunters --out data/legacy-run   # ~10 s
uv run datagen check data/legacy-run --project examples/ecommerce   # laws, expectations, report.html
uv run datagen export data/legacy-run --legacy-fraud --labels xgb --out data/fraud   # scorer labels, 2% bad
uv run bench run data/fraud --oracle

# five-model comparison report (single self-contained HTML, zh or en)
uv run bench compare data/fraud --out reports/payment-risk-benchmark.html \
    --json reports/payment-risk-benchmark.json --lang zh
```

`datagen` is the agentic event simulator: plain Python, one event heap, sized for runs under
about 10⁵ events, with time and memory linear in the events emitted. Projects live in
[`examples/`](examples/README.md); agents author them by following
[`examples/AGENTS.md`](examples/AGENTS.md). `datagen export --legacy-fraud` writes the e-commerce
run in the benchmark's shape: `events.parquet` is the benchmark input; `golden.parquet` holds
hidden golden features and labels' ground truth; `meta.json` records the seed, the source run
(pack, revision, overlay parameters) and the achieved bad rate.

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
