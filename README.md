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
```

`events.parquet` is the benchmark input; `golden.parquet` holds hidden golden features and
labels' ground truth; `meta.json` records seed, config and achieved bad rate.

Note: `--oracle` trains XGBoost on the raw numeric columns plus ALL golden columns, including
`score`, the probability the labels were sampled from. It is therefore a Bayes-style ceiling,
not a realistic "best feature engineering" model.
