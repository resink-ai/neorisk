# bench

Model benchmark runner for synthetic event datasets. Three commands:

- `bench compare`: five models on observable point-in-time features, written up as a single
  self-contained HTML report (plus optional JSON).
- `bench run`: the original two-model raw-column baseline (and the `--oracle` ceiling).
- `bench discover`: label discovery. It hides the ring labels, grows them back from a few
  reported seeds with 11 methods at the same review budget, and scores each method against the
  hidden truth.

## Data

Use scorer labels (`--labels xgb`) for model comparisons. The default role labels are noise-free,
so every model scores AUC ≈ 1 on them. On the `bench` profile (50,000 users, 60 days, seed 42: 45.6k rows), XGB-scorer labels (2.0% bad)
give test AUCs of 0.78–0.82, against a ceiling of 0.836: the AUC of the true probability `score` on
the test split. The test split holds about 95 positives, so AUC differences under about 0.06 are
noise. The profile also blurs the fraud ring (see below), so role labels are no longer trivial:
AUC 0.91–0.94, PR-AUC 0.44–0.52.

The benchmark data is a run of the e-commerce simulation (the `examples/ecommerce` pack with the `bounty_hunters` overlay), exported
in the fraud dataset's shape (D87):

```
uv run datagen run examples/ecommerce --profile bench --overlay bounty_hunters --out data/legacy-run   # ~10 s
uv run datagen export data/legacy-run --legacy-fraud --labels xgb --out data/fraud
```

## Tests

The tests that need data share one session fixture, `legacy_dir` (`tests/legacy_fixture.py`,
registered with `pytest_plugins = ["legacy_fixture"]`): a 2,000-user, 30-day simulation exported for bench, built in about a second.

## `bench compare`

```
uv run bench compare DATA_DIR --out report.html [--json metrics.json] \
    [--models logreg,rf,xgb,ann_small,ann_large] [--shap-rows 5000] [--ann-shap-rows 1000] \
    [--seed 0] [--lang zh|en]
```

Only `events.parquet` and `meta.json` are read; **`golden.parquet` is never opened** (a test
guards this), and loading fails if any `meta.json["golden_columns"]` column leaks into
`events.parquet`. Labels, golden columns and `*_id` columns are never model inputs.

Pipeline: build features -> chronological 60/20/20 split -> train -> score valid/test ->
metrics -> SHAP -> report. The valid split is used only for early stopping and to pick the
best-F1 threshold shown as the operating point; every headline metric is on test.

### Models

| key | model | notes |
|---|---|---|
| `logreg` | Logistic Regression | standardized inputs, `class_weight="balanced"` |
| `rf` | Random Forest | 300 trees, depth 12, `min_samples_leaf=20`, balanced subsample |
| `xgb` | XGBoost | hist, depth 6, lr 0.05, up to 1000 rounds, unweighted (`scale_pos_weight=1`), early stopping on valid PR-AUC with patience 50; the "rounds/epochs" column shows best iteration + 1 |
| `ann_small` | MLP `(32, 16)` | standardized inputs, early stopping on valid AUC (patience 5) |
| `ann_large` | MLP `(256, 128, 64)` | `alpha=1e-4`, same early stopping |

A model that fails to train (or a SHAP failure) is reported in the page instead of aborting
the run.

### Observable features (`bench/features.py`)

All engineered features are strictly point-in-time over `[t - w, t)` with `w` in 7/14/30 days:

- `obs_u_amt_{count,sum,mean,max,min}_{7,14,30}d`: the user's transaction amounts;
- `obs_dev_users_n_unique_7d`: distinct users on the device;
- `obs_u_state_n_unique_30d`: the user's distinct states (location churn);
- `obs_invr_bonus_{count,sum,mean,max}_{7,14,30}d`: the user's own invites as an inviter;
- `obs_inv_bonus_{count,sum,mean,max}_30d`: the inviter's activity as of the invite that brought
  the user in;
- `obs_amt_ratio_30d`: amount relative to the user's 30-day mean;
- the raw numeric event columns (minus near-unique identifier-like ints: `user_street`,
  `user_zip`, `device_ip` and `product_launch_day`, a near-unique product proxy).

### Runtime

Measured on an Apple-silicon laptop, 500k events (seed 42) with defaults: about 3 min 10 s
wall clock. Features 0.4 s; training 41 s in total (LR 0.7 s, RF 10 s, XGBoost 0.9 s, ANN small
7 s, ANN large 22 s); SHAP is the slowest stage, dominated by exact TreeSHAP on the Random
Forest (~140 s for 5,000 rows; KernelSHAP on the ANNs takes a few seconds at 1,000 rows). The
report's run-details section records the per-stage and per-model seconds. Lower `--shap-rows`
to cut the RF TreeSHAP cost (`--ann-shap-rows` only affects the ANNs). "Predict test s" times
the test split only.

### Reproducibility

Runs are seeded and deterministic except for these known, cosmetic effects:

- Random Forest `n_jobs=-1`: tree-building order can change the last decimals of the mean
  predicted probability (and, rarely, a metric's last digit) between runs.
- ANN KernelSHAP (`nsamples=1000`, k-means background) is seeded through the global NumPy
  state; on a 30k-event dataset two same-seed runs, in-process and across processes, were
  bit-identical. Different BLAS builds or thread counts may still perturb the last digits.
- Wall-clock seconds always vary.

### Reading the report

1. **Summary**: AUC, PR-AUC, KS, recall at 50%/80% precision, top-1% precision and lift,
   train/infer seconds; best value per column in bold.
2. **ROC / PR curves**: all models overlaid; the PR baseline is the test positive rate.
3. **Metrics / operating point**: column-normalised heatmap and the confusion matrix at the
   valid-chosen best-F1 threshold.
4. **Calibration**: mean predicted probability vs observed positive rate per quantile bin.
   Logistic Regression and RF are class-weighted and over-predict; XGBoost and the ANNs are
   unweighted. Log loss, Brier and calibration are therefore **not comparable** across the two
   groups (shown as n/c, never bolded); compare on ranking metrics (AUC, PR-AUC, KS,
   recall@precision, top-k).
5. **SHAP**: cross-model normalised importance, then per model the top features and their SHAP
   value distribution. Units differ (log-odds for linear/XGBoost, probability for RF/ANNs),
   so compare rankings, not raw magnitudes. The explained sample is positive-enriched (up to 50%
   positives vs the base rate), so mean|SHAP| describes that sample. KernelSHAP uses a 10-centroid
   k-means background and 1,000 coalition samples.
6. **Run details**: data dir, split sizes, bad rate, feature list, stage and per-model timings,
   ANN epochs.

## `bench run`

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

## Feature allowlist

`meta.json["feature_allowlist"]`, when present, is an upper bound on the raw model inputs: it
must name existing event columns and none may be `label`, a golden column, an `*_id` column or
an engine column (`lamport, partition_id, seq, cause_id, action_id`); otherwise loading fails.
Without it the default is every numeric column except those. `datagen export --legacy-fraud`
writes the allowlist equal to the default raw set (the numeric event columns other than `label`
and `*_id`).

## About `--oracle`

`--oracle` trains XGBoost on the raw numeric columns plus all golden columns **except `score`**
(the probability the labels were sampled from; it stays in `golden.parquet` but is not a
feature). The resulting model is a golden-feature ceiling, not a realistic upper bound for
engineered features. In the legacy export `score` equals `label`, and `actor_role` and
`invitee_is_zombie` are the overlay's ground truth, so the oracle is close to a label leak.

## `bench discover`

```
uv run bench discover --generate examples/ecommerce --profile bench --overlay bounty_hunters \
    --seed 42 --out OUT [--lang zh|en]                 # simulates into OUT/run first, ~40 s total
uv run bench discover --run RUN_DIR --out OUT          # an existing run
    [--methods random,perfect,connection,...] [--k 50] [--rounds 10] [--sweep 0,2,5,10]
    [--seed-draws 5] [--n-seeds 5] [--report-day 45] [--set K=V]
```

Outputs:
- `OUT/discover.json`: every metric, for each method, budget and seed draw (mean and spread).
- `OUT/discover.html`: one page. It has the leaderboard, discovery curves, budget sweep, ROC and
  PR side by side, stealth and visible recall, and approval rate against bad share.

Methods see only a leak-free world (`bench.discover.world`):
- every id is permuted;
- `partition_id`, `action_id`, `cause_id` and `seq` are dropped;
- labels and cases are hidden.

A simulated reviewer (`Oracle`) reveals the true label of up to `k` users per round. Seeds are
visible (non-stealth) ring members whose label is known by `--report-day`. Labels arrive 30 days
after the act, so earlier days have few candidates. Design and results:
`docs/superpowers/specs/2026-10-21-label-discovery-bench-design.md`.
