# neorisk

Python monorepo managed with [uv](https://docs.astral.sh/uv/) workspaces.

```
libs/   shared libraries   (each has its own pyproject.toml)
apps/   applications       (depend on libs via `workspace = true`)
```

Apps consume libs from the local workspace — no PyPI involved.

## Common tasks

```sh
uv sync --all-packages               # install every app and lib into the root .venv
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

## Spider2 reference datasets

```sh
uv run refdata fetch                          # 30 Spider 2.0 SQLite databases → data/spider2/
uv run refdata roundtrip datasets/olist       # real tables → simkit event log → the same tables
```

Thirteen datasets in [`datasets/`](datasets/README.md) take real tables from the Spider 2.0 text-to-SQL benchmark and declare the event log behind them: `olist`, `delivery_center`, `airlines`, `databank`, `cliquebait`, `sakila`, `bitcoin`, `weblog`, `pizzarunner`, `chinook`, `northwind`, `oraclesh` and `adventureworks`. [`refdata`](apps/refdata/README.md) ingests the tables as a simkit dataset and rebuilds them from it. It proves the round trip exact, row for row, and runs the benchmark's own questions on both sides. All derived files stay in the git-ignored `data/`, because the sources' licences vary.

## Ethereum data collection

```sh
uv run eth-collect labels            # every public label source -> data/eth/labels/
uv run eth-collect sample toy        # ~1,000 addresses (seeded + random), latest 5 transfers each
uv run eth-collect status            # last runs, table sizes, toy-sample checks
```

One connector per source in [`apps/ethcollect`](apps/ethcollect/README.md); agents drive it through
the `eth-collect` skill (`.claude/skills/eth-collect/`). Without keys, address history comes
from whole-day scans of the AWS public dataset; a free `ETHERSCAN_API_KEY` gives full histories.

## Ethereum bad-address model (v0)

```sh
uv run ethmodel pretrain && uv run ethmodel embed   # pre-train the encoder, embed every address
uv run ethmodel expand                              # recall on held-out labels + candidates.csv
```

A small transformer pre-trained on transfers, a positive-unlabeled head and label expansion,
in [`apps/ethmodel`](apps/ethmodel/README.md). It reads the toy sample above.

## Large data storage (nds)

`data/` is git-ignored and holds gigabytes that are costly to rebuild. [`nds`](apps/nds/README.md) parks
it on a local folder (`~/data`) or another machine over ssh, and leaves symlinks so the repo paths keep
working: `uv run --package nds nds -C data push --all -r desktop`. One `data/nds.yaml` can manage many
datasets, each with its own include/exclude globs. Design:
[`docs/superpowers/specs/2026-11-06-nds-cli-design.html`](docs/superpowers/specs/2026-11-06-nds-cli-design.html).

## Licence

MIT, see [LICENSE](LICENSE). Spider 2.0 databases and gold answers are not redistributed here; they are fetched from the Spider2 project and keep their own terms (`uv run refdata fetch`).
