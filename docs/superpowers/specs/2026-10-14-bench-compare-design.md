# Multi-Model Benchmark Comparison Report — Design

Date: 2026-10-14
Status: Draft for review
Builds on: `docs/superpowers/specs/2026-10-13-ml-sim-datagen-design.md` (PR #1, `feat/ml-sim-datagen`)

## 1. Goal

Benchmark five model types on a 500k-event payment-transaction risk dataset and show them
side by side in one self-contained HTML report: ROC and PR curves, SHAP feature
contribution/importance, and other critical classification metrics. The benchmark answers
"which model best recovers fraud from what a real risk team could observe".

### Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Data | Reuse the existing fraud (payment transaction) scenario: `datagen generate --n-events 500000`. No new generator. |
| Models | Logistic Regression, Random Forest, XGBoost, small ANN, large ANN. (SVM was dropped: kernel SVM is infeasible at 500k rows; Logistic Regression replaces it as the classic risk-scorecard baseline.) |
| Features | Models train on **observable** point-in-time features engineered from `events.parquet` only. Golden features remain hidden from every model. |
| Placement | Extend `apps/bench` (reuses loader, guards, time split, `simkit.rolling`/`rolling_asof`). |
| Report | One self-contained HTML (inline SVG, no network) + `metrics.json`. |

## 2. Data

`datagen generate --scenario fraud --n-events 500000 --seed 42 --out data/fraud500k`
(about 25k users, 20k devices; bad rate 2% by default). The scenario already provides
slow/fast attributes, bursty activity, warm-up/cash-out, device-sharing rings and
bounty-hunter/zombie invite linkage (`inviter_id` reference column).

Split: chronological 60/20/20 by `event_time` (existing `time_split`). Hyperparameters
are fixed; the valid split is used only for early stopping (XGBoost, ANNs).

## 3. Observable feature layer (`bench/features.py`)

Computed only from columns present in `events.parquet`, strictly before event time
(window `[t - w, t)`), over the full table and then split by time. No label, no golden
column, no `*_id` string reaches a model.

| Group | Features |
|---|---|
| User velocity (txn rows) | count, sum, mean, max, min of `amount` over 7/14/30d; `amount / (mean_30d + 1)` |
| Device sharing | distinct `user_id` per `device_id` over 7d |
| Address churn | distinct `user_state` per user over 30d |
| Inviter side (by `inviter_id`) | invites, bonus sum/mean/max over 7/14/30d, attached to the inviter's own events (via `rolling_asof`) |
| Invitee side | the inviter's recent invite activity as of the invite, looked up for the invitee's events |
| Raw columns | numeric event/entity attributes, `event_type`, `amount`, `referral_bonus`, etc. |

String IDs are used only as grouping keys, then dropped. Nulls/NaN are filled with -1
(trees) and standardized after filling (LR/ANN). A brute-force test verifies
point-in-time correctness on a sample.

## 4. Models (`bench/models.py`)

| Model | Implementation | Key settings |
|---|---|---|
| Logistic Regression | `sklearn` `LogisticRegression` in a `StandardScaler` pipeline | `class_weight="balanced"`, `max_iter=1000` |
| Random Forest | `sklearn` `RandomForestClassifier` | 300 trees, `max_depth=12`, `min_samples_leaf=20`, `class_weight="balanced_subsample"`, `n_jobs=-1` |
| XGBoost | `xgboost` `XGBClassifier` | `scale_pos_weight = neg/pos`, depth 6, `eta=0.1`, up to 500 rounds, early stopping on valid |
| ANN small | `sklearn` `MLPClassifier` (inputs standardized) | hidden `(32, 16)`, early stopping |
| ANN large | `sklearn` `MLPClassifier` (inputs standardized) | hidden `(256, 128, 64)`, `alpha=1e-4`, early stopping |

All seeded (`random_state`) and single-process deterministic where the library allows
(documented where it does not). Probabilities from every model are used for all metrics.
ANN sizes rationale: the small net is a low-capacity reference; the large net is wide
enough to capture interactions on ~25 features without needing GPU or a torch dependency.

## 5. Metrics (`bench/metrics.py`)

Per model, on the test split (valid also stored):
- ROC-AUC and PR-AUC, plus the full ROC and PR curves (downsampled to <= 500 points)
- Recall at precision 0.5 and 0.8; precision at top 0.5% and 1% of scores; lift@1%
- KS statistic
- Log loss and Brier score; calibration curve (10 quantile bins)
- Confusion matrix and precision/recall/F1 at the threshold maximizing F1 on valid
- Train time and inference time (seconds)

Single-class splits yield NaN metrics, not exceptions (existing contract).

## 6. Explainability (`bench/explain.py`)

Uses `shap`. Computed on a fixed stratified sample of the test split (default 5,000 rows,
all positives kept up to the cap) so cost is bounded.

| Model | Explainer |
|---|---|
| Random Forest, XGBoost | `TreeExplainer` |
| Logistic Regression | `LinearExplainer` |
| ANN small/large | sampled permutation/kernel explainer, 100 background rows, <= 1,000 explained rows |

Outputs per model: mean |SHAP| importance per feature, and per-feature SHAP value
distribution (quantiles + a downsampled point set for the strip/beeswarm plot).
Cross-model view: normalized importance rank table of the union of top features.

## 7. Report (`bench/report.py`, CLI `bench compare`)

`bench compare DATA_DIR --out report.html [--json metrics.json] [--shap-rows N] [--models a,b,c]`

Single HTML, inline SVG, light/dark friendly, no external assets. Sections:
1. Summary table (all models x headline metrics, best per column highlighted)
2. ROC curves overlay and PR curves overlay (with positive-rate baseline)
3. Metrics heatmap (models x metrics) and operating-point table
4. Calibration curves
5. SHAP: cross-model importance comparison, then per-model distribution plots
6. Run details: data path, n_events, split sizes, bad rate, feature list, seeds, timings

`metrics.json` carries every number plotted, for downstream use.

## 8. Error handling

- Reuse `load_events` guards (label required, `golden_columns` required, no golden leakage).
- `bench compare` fails fast if the dataset has fewer than N positives in train (default 50)
  or if a split is single-class (reports NaN rows but still renders).
- A model that fails to train is reported in the report as failed with its error; the
  remaining models still run.
- `shap` explanation failures degrade to "SHAP unavailable" for that model only.

## 9. Testing

- Features: point-in-time brute-force check; no golden/label/`*_id` columns in the matrix.
- Models: each returns finite probabilities in [0,1] on a tiny dataset; deterministic
  with a fixed seed.
- Metrics: known-answer cases (perfect/random ranking, single-class NaN).
- Explain: importances finite, sum of |SHAP| consistent with model output ordering
  on a tiny model (additivity check for tree/linear).
- Report: renders for all five models; contains each required section and no network
  references; `metrics.json` round-trips.
- E2E smoke on ~5k events (< 60 s).

## 10. Out of scope

Hyperparameter search, model stacking, GPU/torch models, calibration post-processing,
time-series cross-validation, new scenarios (LTV, growth), changing the generator.
