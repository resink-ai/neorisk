# Multi-Model Benchmark Comparison Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `apps/bench` with a `bench compare` command that trains Logistic Regression, Random Forest, XGBoost and two ANNs on observable point-in-time features of a 500k-event payment-fraud dataset and renders one self-contained HTML report (ROC/PR curves, SHAP, extra metrics) plus `metrics.json`.

**Architecture:** New modules in `apps/bench`: `features` (observable feature layer built on `neorisk_simkit.rolling`/`rolling_asof`), `models` (five seeded model factories + training), `metrics`, `explain` (shap), `report` (inline-SVG HTML), `compare` (orchestrator). Reuses `bench.runner.load_events` / `time_split` guards. No generator changes.

**Tech Stack:** Python 3.12, polars 2.x, numpy, scikit-learn, xgboost, shap, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-14-bench-compare-design.md` (builds on `docs/superpowers/specs/2026-10-13-ml-sim-datagen-design.md`)

## Global Constraints

- Python `>=3.12`; ruff `line-length = 100`; use `uv sync --all-packages`, `uv run ...`.
- Test file basenames must be unique repo-wide (no `__init__.py` in test dirs).
- Features use only columns of `events.parquet`; never label, golden columns, or `*_id` strings as model inputs. Rolling features strictly point-in-time `[t - w, t)`.
- `golden.parquet` is never read by `bench compare`.
- Same seed => same data and same metrics where the libraries allow; document where not.
- Report is a single HTML file with inline CSS/SVG/JS only: no network references.
- Any non-finite metric is written to JSON as `null` (never `NaN`).
- Commit messages end with the session attribution trailers (`Co-Authored-By: ...`, `Claude-Session: ...`).
- Known environment facts: polars 2.0 (cannot build columns from lists of `np.datetime64` scalars; `rolling` output is ordered by `[key, time]` so always join back on id), xgboost 3.x, scikit-learn 1.9.

## Review Focus

Failure modes the spec implies but straight-line code tends to miss (each is pinned by a test in the owning task):
1. **Feature leakage**: label/golden/`*_id` columns in the matrix; features that change when labels are shuffled (Task 1).
2. **Few positives / single-class split**: metrics are NaN, report still renders, no exception (Tasks 3, 6).
3. **One model failing** (training or SHAP error) must not kill the run or the report (Task 6).
4. **NaN/inf in JSON** and **HTML escaping** of feature/model names (Task 5).
5. **Zero-variance / constant feature columns** in scaling and SHAP produce no NaN/inf (Tasks 2, 4).

## File Structure

```
apps/bench/
  pyproject.toml                          (modify: deps shap, neorisk-simkit)
  src/bench/features.py                   observable feature layer
  src/bench/models.py                     model factories, FittedModel, train_all
  src/bench/metrics.py                    compute_metrics, best_f1_threshold
  src/bench/explain.py                    shap importance + distributions
  src/bench/report.py                     SVG helpers + render_report
  src/bench/compare.py                    run_compare orchestrator + write_outputs
  src/bench/cli.py                        (modify: add `compare`)
  tests/test_bench_{features,models,metrics,explain,report,compare}.py
  README.md                               (modify)
```

---

### Task 1: Dependencies and observable feature layer

**Files:**
- Modify: `apps/bench/pyproject.toml`
- Create: `apps/bench/src/bench/features.py`
- Test: `apps/bench/tests/test_bench_features.py`

**Interfaces:**
- Produces:
  - `WINDOWS = (7, 14, 30)`, `IDENTIFIER_LIKE = ("user_street", "user_zip", "device_ip")`
  - `build_features(events: pl.DataFrame) -> pl.DataFrame`: columns `event_id` + numeric feature columns, same row order as `events`, no nulls/NaN.
  - `feature_names(features: pl.DataFrame) -> list[str]`: all columns except `event_id`.
- Engineered columns: `obs_u_amt_{count,sum,mean,max,min}_{7,14,30}d`, `obs_dev_users_n_unique_7d`, `obs_u_state_n_unique_30d`, `obs_invr_bonus_{count,sum,mean,max}_{7,14,30}d`, `obs_inv_bonus_{count,sum,mean,max}_30d`, `obs_amt_ratio_30d`; plus raw numeric columns (excluding `label`, `event_id`, `*_id`, identifier-like columns).

- [ ] **Step 1: Add dependencies**

In `apps/bench/pyproject.toml` set:
```toml
dependencies = ["neorisk-simkit", "numpy>=1.26", "polars>=1.0", "scikit-learn>=1.4", "shap>=0.46", "xgboost>=2.0"]
```
and add `neorisk-simkit = { workspace = true }` under `[tool.uv.sources]`.
Run: `uv sync --all-packages && uv run python -c "import shap, neorisk_simkit; print(shap.__version__)"`
Expected: prints a shap version. If shap import fails against numpy/numba, report; do not pin numpy down without noting it.

- [ ] **Step 2: Write the failing tests**

```python
import numpy as np
import polars as pl
import pytest
from datagen.config import FraudConfig
from datagen.scenarios.fraud import generate

from bench.features import IDENTIFIER_LIKE, build_features, feature_names


@pytest.fixture(scope="module")
def events():
    return generate(FraudConfig(n_events=5000, seed=5, span_days=40)).events


@pytest.fixture(scope="module")
def feats(events):
    return build_features(events)


def test_rows_align_with_events_and_no_nulls(events, feats):
    assert feats["event_id"].equals(events["event_id"])
    names = feature_names(feats)
    assert names and all(feats.schema[c].is_numeric() for c in names)
    assert feats.select(pl.col(names).is_null().sum()).row(0) == (0,) * len(names)
    floats = [c for c in names if feats.schema[c].is_float()]
    assert feats.select(pl.col(floats).is_nan().sum()).row(0) == (0,) * len(floats)


def test_no_label_golden_or_id_columns(events, feats):
    names = set(feature_names(feats))
    assert "label" not in names and "event_time" not in names
    assert not any(c.endswith("_id") for c in names)
    assert not names & set(IDENTIFIER_LIKE)
    for banned in ("score", "invitee_is_zombie", "amt_ratio_30d"):
        assert banned not in names


def test_features_do_not_depend_on_labels(events, feats):
    shuffled = events.with_columns(
        label=pl.Series(np.random.default_rng(0).permutation(events["label"].to_numpy()))
    )
    assert build_features(shuffled).equals(feats)


def test_velocity_matches_bruteforce(events, feats):
    txn = events.filter(pl.col("event_type") == 0).select("user_id", "event_time", "amount")
    rows = txn.to_dicts()
    by_user: dict[str, list] = {}
    for r in rows:
        by_user.setdefault(r["user_id"], []).append(r)
    joined = events.select("event_id", "user_id", "event_time", "event_type").join(
        feats.select("event_id", "obs_u_amt_count_30d", "obs_u_amt_sum_30d"), on="event_id"
    )
    sample = joined.filter(pl.col("event_type") == 0).head(300).to_dicts()
    from datetime import timedelta

    for r in sample:
        lo = r["event_time"] - timedelta(days=30)
        prior = [x for x in by_user[r["user_id"]] if lo <= x["event_time"] < r["event_time"]]
        assert r["obs_u_amt_count_30d"] == len(prior)
        assert r["obs_u_amt_sum_30d"] == pytest.approx(sum(x["amount"] for x in prior))


def test_inviter_side_counts_invites_before_event(events, feats):
    inv = events.filter(pl.col("event_type") == 1).drop_nulls("inviter_id")
    hunter = inv.group_by("inviter_id").len().sort("len", descending=True)["inviter_id"][0]
    mine = events.filter(pl.col("user_id") == hunter).select("event_id", "event_time")
    got = mine.join(feats.select("event_id", "obs_invr_bonus_count_30d"), on="event_id")
    assert got["obs_invr_bonus_count_30d"].max() > 0


def test_missing_required_column_raises(events):
    with pytest.raises(ValueError, match="inviter_id"):
        build_features(events.drop("inviter_id"))
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest apps/bench/tests/test_bench_features.py -v`
Expected: FAIL (`ModuleNotFoundError: bench.features`)

- [ ] **Step 4: Implement**

```python
import polars as pl
from neorisk_simkit import rolling, rolling_asof

WINDOWS = (7, 14, 30)
IDENTIFIER_LIKE = ("user_street", "user_zip", "device_ip")  # near-unique ints act like IDs
_REQUIRED = (
    "event_id", "event_time", "event_type", "user_id", "device_id", "inviter_id",
    "amount", "referral_bonus", "user_state",
)


def feature_names(features: pl.DataFrame) -> list[str]:
    return [c for c in features.columns if c != "event_id"]


def _raw_columns(events: pl.DataFrame) -> list[str]:
    skip = {"label", "event_id", "event_time", *IDENTIFIER_LIKE}
    return [
        c
        for c, t in events.schema.items()
        if t.is_numeric() and c not in skip and not c.endswith("_id")
    ]


def build_features(events: pl.DataFrame) -> pl.DataFrame:
    """Observable point-in-time features from ``events`` only (no label, no golden columns).

    Output: ``event_id`` + numeric features, same row order as ``events``, nulls/NaN filled
    (engineered -> 0, raw -> -1).
    """
    missing = [c for c in _REQUIRED if c not in events.columns]
    if missing:
        raise ValueError(f"events is missing required columns: {missing}")
    ev = events.with_columns(pl.col("user_id").hash().alias("_user_code"))
    txn = ev.filter(pl.col("event_type") == 0)
    inv = ev.filter((pl.col("event_type") == 1) & pl.col("inviter_id").is_not_null())

    vel = rolling(
        txn, key="user_id", value="amount", windows_days=WINDOWS,
        aggs=["count", "sum", "mean", "max", "min"], prefix="obs_u_amt",
    )
    devu = rolling(
        txn, key="device_id", value="_user_code", windows_days=[7], aggs=["n_unique"],
        prefix="obs_dev_users",
    )
    churn = rolling(
        txn, key="user_id", value="user_state", windows_days=[30], aggs=["n_unique"],
        prefix="obs_u_state",
    )
    # a user's own activity as an inviter, evaluated exactly at each of the user's events
    invr = rolling_asof(
        ev.select("event_id", "user_id", "event_time"),
        inv.select("inviter_id", "event_time", "referral_bonus"),
        query_key="user_id", source_key="inviter_id", value="referral_bonus",
        windows_days=WINDOWS, aggs=["count", "sum", "mean", "max"], prefix="obs_invr_bonus",
    )
    # the inviter's recent invite activity as of the invite that brought a user in
    g = rolling(
        inv, key="inviter_id", value="referral_bonus", windows_days=[30],
        aggs=["count", "sum", "mean", "max"], prefix="obs_inv_bonus",
    )
    inv_feats = (
        inv.select("event_id", "user_id", "event_time")
        .join(g, on="event_id", how="left", maintain_order="left")
        .drop("event_id")
        .sort("event_time")
    )
    invitee = (
        ev.select("event_id", "user_id", "event_time")
        .sort("event_time")
        .join_asof(inv_feats, on="event_time", by="user_id", strategy="backward",
                   check_sortedness=False)
        .drop("user_id", "event_time")
    )

    out = ev.select("event_id")
    for part in (vel, devu, churn, invr, invitee):
        out = out.join(part, on="event_id", how="left", maintain_order="left")
    engineered = [c for c in out.columns if c != "event_id"]
    out = out.with_columns(pl.col(engineered).fill_null(0))
    out = out.join(ev.select("event_id", "amount"), on="event_id", how="left", maintain_order="left")
    out = out.with_columns(
        obs_amt_ratio_30d=pl.col("amount").fill_null(0.0) / (pl.col("obs_u_amt_mean_30d") + 1.0)
    ).drop("amount")

    raw = _raw_columns(events)
    floats = [c for c in raw if events.schema[c].is_float()]
    raw_df = ev.select("event_id", *raw)
    if floats:
        raw_df = raw_df.with_columns(pl.col(floats).fill_nan(None))
    raw_df = raw_df.with_columns(pl.col(raw).fill_null(-1))
    return out.join(raw_df, on="event_id", how="left", maintain_order="left")
```

- [ ] **Step 5: Run to verify pass, lint**

Run: `uv run pytest apps/bench/tests/test_bench_features.py -v && uv run ruff check apps/bench && uv run ruff format apps/bench`
Expected: all pass. If `obs_*` names collide with raw column names or join order differs, fix in the module, not the tests.

- [ ] **Step 6: Commit**

```bash
git add apps/bench uv.lock
git commit -m "feat(bench): observable point-in-time feature layer"
```

---

### Task 2: Models

**Files:**
- Create: `apps/bench/src/bench/models.py`
- Test: `apps/bench/tests/test_bench_models.py`

**Interfaces:**
- Produces:
  - `MODEL_ORDER = ("logreg", "rf", "xgb", "ann_small", "ann_large")`, `DISPLAY = {...}` (human names)
  - `FittedModel(name, kind, estimator, scaler, train_seconds)` with `.transform(X)`, `.predict_proba(X) -> np.ndarray[float]` (positive-class probability); `kind` in `{"linear", "tree", "xgb", "ann"}`
  - `ModelFailure(name, error: str)`
  - `train_all(X_train, y_train, X_valid, y_valid, *, names=MODEL_ORDER, seed=0) -> dict[str, FittedModel | ModelFailure]`

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pytest

from bench.models import MODEL_ORDER, FittedModel, ModelFailure, train_all


def _data(n=3000, seed=0):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 4))
    x[:, 3] = 1.0  # constant column (zero variance)
    logit = 2.0 * x[:, 0] - 1.0 * x[:, 1] - 3.0
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    return x, y


def test_all_five_models_train_and_predict_probabilities():
    x, y = _data()
    tr, va = slice(0, 2000), slice(2000, 3000)
    res = train_all(x[tr], y[tr], x[va], y[va], seed=1)
    assert list(res) == list(MODEL_ORDER)
    for name, m in res.items():
        assert isinstance(m, FittedModel), (name, getattr(m, "error", None))
        p = m.predict_proba(x[va])
        assert p.shape == (1000,) and np.isfinite(p).all()
        assert p.min() >= 0 and p.max() <= 1
        assert m.train_seconds >= 0


def test_models_beat_chance_on_signal():
    from sklearn.metrics import roc_auc_score

    x, y = _data(6000, seed=3)
    tr, te = slice(0, 4000), slice(4000, 6000)
    res = train_all(x[tr], y[tr], x[tr], y[tr], seed=0)
    for name, m in res.items():
        assert roc_auc_score(y[te], m.predict_proba(x[te])) > 0.7, name


def test_deterministic_with_seed():
    x, y = _data()
    a = train_all(x[:2000], y[:2000], x[2000:], y[2000:], names=("logreg", "ann_small"), seed=4)
    b = train_all(x[:2000], y[:2000], x[2000:], y[2000:], names=("logreg", "ann_small"), seed=4)
    for n in a:
        assert np.allclose(a[n].predict_proba(x[2000:]), b[n].predict_proba(x[2000:]))


def test_failure_is_captured_not_raised(monkeypatch):
    import bench.models as m

    def boom(*a, **k):
        raise RuntimeError("kaput")

    monkeypatch.setitem(m._FACTORIES, "rf", boom)
    x, y = _data()
    res = train_all(x[:2000], y[:2000], x[2000:], y[2000:], names=("logreg", "rf"), seed=0)
    assert isinstance(res["logreg"], FittedModel)
    assert isinstance(res["rf"], ModelFailure) and "kaput" in res["rf"].error


def test_single_class_train_is_a_failure_not_a_crash():
    x, _ = _data()
    y = np.zeros(len(x), dtype=int)
    res = train_all(x[:2000], y[:2000], x[2000:], y[2000:], names=("logreg",), seed=0)
    assert isinstance(res["logreg"], ModelFailure)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest apps/bench/tests/test_bench_models.py -v`
Expected: FAIL (`ModuleNotFoundError: bench.models`)

- [ ] **Step 3: Implement**

```python
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

MODEL_ORDER = ("logreg", "rf", "xgb", "ann_small", "ann_large")
DISPLAY = {
    "logreg": "Logistic Regression",
    "rf": "Random Forest",
    "xgb": "XGBoost",
    "ann_small": "ANN small (32-16)",
    "ann_large": "ANN large (256-128-64)",
}
_KIND = {"logreg": "linear", "rf": "tree", "xgb": "xgb", "ann_small": "ann", "ann_large": "ann"}
_SCALED = {"logreg", "ann_small", "ann_large"}


@dataclass
class FittedModel:
    name: str
    kind: str
    estimator: Any
    scaler: StandardScaler | None
    train_seconds: float

    def transform(self, x: np.ndarray) -> np.ndarray:
        return x if self.scaler is None else self.scaler.transform(x)

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        return self.estimator.predict_proba(self.transform(x))[:, 1].astype("float64")


@dataclass
class ModelFailure:
    name: str
    error: str


def _logreg(seed, pos_weight):
    return LogisticRegression(max_iter=1000, class_weight="balanced", random_state=seed)


def _rf(seed, pos_weight):
    return RandomForestClassifier(
        n_estimators=300, max_depth=12, min_samples_leaf=20,
        class_weight="balanced_subsample", n_jobs=-1, random_state=seed,
    )


def _xgb(seed, pos_weight):
    return XGBClassifier(
        n_estimators=500, max_depth=6, learning_rate=0.1, scale_pos_weight=pos_weight,
        eval_metric="aucpr", early_stopping_rounds=30, tree_method="hist", random_state=seed,
    )


def _ann(hidden, alpha):
    def make(seed, pos_weight):
        return MLPClassifier(
            hidden_layer_sizes=hidden, alpha=alpha, batch_size=1024, max_iter=60,
            early_stopping=True, n_iter_no_change=5, random_state=seed,
        )

    return make


_FACTORIES = {
    "logreg": _logreg,
    "rf": _rf,
    "xgb": _xgb,
    "ann_small": _ann((32, 16), 1e-4),
    "ann_large": _ann((256, 128, 64), 1e-4),
}


def train_all(x_train, y_train, x_valid, y_valid, *, names=MODEL_ORDER, seed: int = 0):
    """Train each model; a failing model becomes a ``ModelFailure`` (never raises)."""
    out: dict[str, FittedModel | ModelFailure] = {}
    y_train = np.asarray(y_train)
    for name in names:
        try:
            if len(np.unique(y_train)) < 2:
                raise ValueError("training labels contain a single class")
            pos = max(int(y_train.sum()), 1)
            pos_weight = max((len(y_train) - pos) / pos, 1.0)
            est = _FACTORIES[name](seed, pos_weight)
            scaler = None
            xt, xv = x_train, x_valid
            if name in _SCALED:
                scaler = StandardScaler().fit(x_train)
                xt, xv = scaler.transform(x_train), scaler.transform(x_valid)
            t0 = time.perf_counter()
            if name == "xgb":
                est.fit(xt, y_train, eval_set=[(xv, y_valid)], verbose=False)
            else:
                est.fit(xt, y_train)
            out[name] = FittedModel(
                name, _KIND[name], est, scaler, time.perf_counter() - t0
            )
        except Exception as e:  # noqa: BLE001 - isolate per-model failures
            out[name] = ModelFailure(name, f"{type(e).__name__}: {e}")
    return out
```
Note: a constant (zero-variance) column makes `StandardScaler` divide by 1 (sklearn handles it), so no NaN.

- [ ] **Step 4: Run to verify pass, lint**

Run: `uv run pytest apps/bench/tests/test_bench_models.py -v && uv run ruff check apps/bench && uv run ruff format apps/bench`
Expected: 5 passed. If `test_deterministic_with_seed` fails for `ann_small` due to library nondeterminism, set `n_jobs`-free paths only; if still nondeterministic compare with `atol=1e-6` and note it.

- [ ] **Step 5: Commit**

```bash
git add apps/bench
git commit -m "feat(bench): five seeded models with isolated failures"
```

---

### Task 3: Metrics

**Files:**
- Create: `apps/bench/src/bench/metrics.py`
- Test: `apps/bench/tests/test_bench_metrics.py`

**Interfaces:**
- Produces:
  - `compute_metrics(y, p, *, threshold: float | None = None, max_curve_points: int = 500) -> dict` with keys `n, n_pos, auc, pr_auc, recall_at_p50, recall_at_p80, precision_top_0_5pct, precision_top_1pct, lift_top_1pct, ks, log_loss, brier, roc_curve {fpr, tpr}, pr_curve {recall, precision}, calibration [{mean_pred, frac_pos, count}], confusion {threshold, tn, fp, fn, tp, precision, recall, f1} | None`
  - `best_f1_threshold(y, p) -> float`
  - Single-class `y` => all scalar metrics `float("nan")`, curves empty, `confusion` None.

- [ ] **Step 1: Write the failing tests**

```python
import math

import numpy as np
import pytest

from bench.metrics import best_f1_threshold, compute_metrics


def test_perfect_ranking():
    y = np.array([0] * 90 + [1] * 10)
    p = np.concatenate([np.linspace(0, 0.4, 90), np.linspace(0.6, 1, 10)])
    m = compute_metrics(y, p, threshold=0.5)
    assert m["auc"] == 1.0 and m["pr_auc"] == pytest.approx(1.0)
    assert m["recall_at_p80"] == 1.0 and m["ks"] == pytest.approx(1.0)
    assert m["precision_top_1pct"] == 1.0 and m["lift_top_1pct"] == pytest.approx(10.0)
    c = m["confusion"]
    assert (c["tp"], c["fp"], c["fn"], c["tn"]) == (10, 0, 0, 90)
    assert c["f1"] == 1.0


def test_random_ranking_near_chance():
    rng = np.random.default_rng(0)
    y = (rng.random(20000) < 0.05).astype(int)
    m = compute_metrics(y, rng.random(20000))
    assert 0.47 < m["auc"] < 0.53
    assert m["pr_auc"] == pytest.approx(0.05, abs=0.02)
    assert m["confusion"] is None


def test_single_class_gives_nan_not_exception():
    m = compute_metrics(np.zeros(10, dtype=int), np.linspace(0, 1, 10), threshold=0.5)
    assert math.isnan(m["auc"]) and math.isnan(m["pr_auc"]) and math.isnan(m["log_loss"])
    assert m["roc_curve"] == {"fpr": [], "tpr": []} and m["confusion"] is None


def test_curves_downsampled_and_bounded():
    rng = np.random.default_rng(1)
    y = (rng.random(50000) < 0.1).astype(int)
    p = np.clip(y * 0.3 + rng.random(50000) * 0.7, 0, 1)
    m = compute_metrics(y, p, max_curve_points=200)
    assert len(m["roc_curve"]["fpr"]) <= 200 and len(m["pr_curve"]["recall"]) <= 200
    assert m["roc_curve"]["fpr"][0] == 0 and m["roc_curve"]["tpr"][-1] == 1


def test_calibration_bins_cover_all_rows_and_monotone_rate_for_calibrated_scores():
    rng = np.random.default_rng(2)
    p = rng.random(30000)
    y = (rng.random(30000) < p).astype(int)
    m = compute_metrics(y, p)
    cal = m["calibration"]
    assert sum(b["count"] for b in cal) == 30000 and 5 <= len(cal) <= 10
    assert all(abs(b["mean_pred"] - b["frac_pos"]) < 0.05 for b in cal)
    assert m["brier"] < 0.2 and m["log_loss"] > 0


def test_best_f1_threshold_prefers_separating_point():
    y = np.array([0, 0, 0, 0, 1, 1])
    p = np.array([0.1, 0.2, 0.3, 0.4, 0.8, 0.9])
    t = best_f1_threshold(y, p)
    assert 0.4 < t <= 0.8
    assert best_f1_threshold(np.zeros(5, dtype=int), np.linspace(0, 1, 5)) == 0.5
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest apps/bench/tests/test_bench_metrics.py -v`
Expected: FAIL (`ModuleNotFoundError: bench.metrics`)

- [ ] **Step 3: Implement**

```python
import math

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)

_SCALARS = (
    "auc", "pr_auc", "recall_at_p50", "recall_at_p80", "precision_top_0_5pct",
    "precision_top_1pct", "lift_top_1pct", "ks", "log_loss", "brier",
)


def _downsample(*arrays, max_points: int):
    n = len(arrays[0])
    if n <= max_points:
        return [a.tolist() for a in arrays]
    idx = np.unique(np.linspace(0, n - 1, max_points).astype(int))
    return [a[idx].tolist() for a in arrays]


def _recall_at_precision(prec, rec, floor):
    ok = prec >= floor
    return float(rec[ok].max()) if ok.any() else 0.0


def _precision_top(y, p, frac):
    k = max(1, int(math.ceil(frac * len(y))))
    idx = np.argsort(-p, kind="stable")[:k]
    return float(y[idx].mean())


def _calibration(y, p, bins=10):
    edges = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return [{"mean_pred": float(p.mean()), "frac_pos": float(y.mean()), "count": len(y)}]
    which = np.clip(np.searchsorted(edges[1:-1], p, side="right"), 0, len(edges) - 2)
    out = []
    for b in range(len(edges) - 1):
        m = which == b
        if m.any():
            out.append(
                {"mean_pred": float(p[m].mean()), "frac_pos": float(y[m].mean()), "count": int(m.sum())}
            )
    return out


def best_f1_threshold(y, p) -> float:
    y = np.asarray(y).astype(int)
    p = np.asarray(p, dtype="float64")
    if len(np.unique(y)) < 2:
        return 0.5
    prec, rec, thr = precision_recall_curve(y, p)
    f1 = 2 * prec[:-1] * rec[:-1] / np.maximum(prec[:-1] + rec[:-1], 1e-12)
    return float(thr[int(np.argmax(f1))])


def _confusion(y, p, threshold):
    pred = p >= threshold
    tp = int((pred & (y == 1)).sum())
    fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum())
    tn = int((~pred & (y == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": float(threshold), "tn": tn, "fp": fp, "fn": fn, "tp": tp,
        "precision": precision, "recall": recall, "f1": f1,
    }


def compute_metrics(y, p, *, threshold: float | None = None, max_curve_points: int = 500) -> dict:
    y = np.asarray(y).astype(int)
    p = np.asarray(p, dtype="float64")
    out: dict = {"n": int(len(y)), "n_pos": int(y.sum())}
    if len(np.unique(y)) < 2:
        out.update({k: float("nan") for k in _SCALARS})
        out.update(
            roc_curve={"fpr": [], "tpr": []},
            pr_curve={"recall": [], "precision": []},
            calibration=[],
            confusion=None,
        )
        return out
    fpr, tpr, _ = roc_curve(y, p)
    prec, rec, _ = precision_recall_curve(y, p)
    eps = 1e-12
    pc = np.clip(p, eps, 1 - eps)
    base = float(y.mean())
    top1 = _precision_top(y, p, 0.01)
    f_fpr, f_tpr = _downsample(fpr, tpr, max_points=max_curve_points)
    f_rec, f_prec = _downsample(rec, prec, max_points=max_curve_points)
    out.update(
        auc=float(roc_auc_score(y, p)),
        pr_auc=float(average_precision_score(y, p)),
        recall_at_p50=_recall_at_precision(prec, rec, 0.5),
        recall_at_p80=_recall_at_precision(prec, rec, 0.8),
        precision_top_0_5pct=_precision_top(y, p, 0.005),
        precision_top_1pct=top1,
        lift_top_1pct=top1 / base if base > 0 else float("nan"),
        ks=float(np.max(tpr - fpr)),
        log_loss=float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))),
        brier=float(np.mean((p - y) ** 2)),
        roc_curve={"fpr": f_fpr, "tpr": f_tpr},
        pr_curve={"recall": f_rec, "precision": f_prec},
        calibration=_calibration(y, p),
        confusion=_confusion(y, p, threshold) if threshold is not None else None,
    )
    return out
```

- [ ] **Step 4: Run to verify pass, lint**

Run: `uv run pytest apps/bench/tests/test_bench_metrics.py -v && uv run ruff check apps/bench && uv run ruff format apps/bench`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add apps/bench
git commit -m "feat(bench): classification metrics, curves, calibration"
```

---

### Task 4: Explainability

**Files:**
- Create: `apps/bench/src/bench/explain.py`
- Test: `apps/bench/tests/test_bench_explain.py`

**Interfaces:**
- Consumes: `FittedModel` (Task 2).
- Produces:
  - `stratified_sample(y, n, rng) -> np.ndarray` (sorted row indices; keeps all positives up to `n // 2`, rest negatives)
  - `explain_model(model: FittedModel, x_train, x_explain, feature_names, *, ann_rows=1000, seed=0, max_points=300) -> dict` with keys `method, n_rows, importance {feature: mean|shap|}, quantiles {feature: [q05,q25,q50,q75,q95]}, points {feature: {"shap": [...], "value": [... normalized 0..1]}}`
  - SHAP values are in the model's own output space (log-odds for linear/xgb, probability for RF/ANN); the report normalizes importances per model.

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pytest

from bench.explain import explain_model, stratified_sample
from bench.models import FittedModel, train_all

NAMES = ["signal", "weak", "noise", "const"]


def _data(n=2500, seed=0):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 4))
    x[:, 3] = 7.0
    logit = 2.5 * x[:, 0] + 0.6 * x[:, 1] - 2.0
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    return x, y


@pytest.fixture(scope="module")
def fitted():
    x, y = _data()
    res = train_all(x[:1800], y[:1800], x[1800:], y[1800:], seed=2)
    assert all(isinstance(m, FittedModel) for m in res.values())
    return res, x, y


@pytest.mark.parametrize("name", ["logreg", "rf", "xgb", "ann_small", "ann_large"])
def test_informative_feature_ranks_first(fitted, name):
    res, x, _ = fitted
    out = explain_model(res[name], x[:1800], x[1800:1950], NAMES, ann_rows=60, seed=0)
    imp = out["importance"]
    assert set(imp) == set(NAMES)
    assert all(np.isfinite(v) and v >= 0 for v in imp.values())
    assert max(imp, key=imp.get) == "signal"
    assert imp["const"] < imp["signal"] * 0.05 + 1e-9
    q = out["quantiles"]["signal"]
    assert len(q) == 5 and q == sorted(q)
    pts = out["points"]["signal"]
    assert len(pts["shap"]) == len(pts["value"]) <= 300
    assert 0 <= min(pts["value"]) and max(pts["value"]) <= 1
    assert out["n_rows"] == 150 or name.startswith("ann")


def test_stratified_sample_keeps_positives_and_is_deterministic():
    rng = np.random.default_rng(0)
    y = np.zeros(10000, dtype=int)
    y[:40] = 1
    a = stratified_sample(y, 200, np.random.default_rng(1))
    b = stratified_sample(y, 200, np.random.default_rng(1))
    assert np.array_equal(a, b) and len(a) == 200
    assert y[a].sum() == 40
    assert np.array_equal(a, np.sort(a))


def test_sample_smaller_than_cap_returns_everything():
    y = np.array([0, 1, 0, 1])
    assert stratified_sample(y, 100, np.random.default_rng(0)).tolist() == [0, 1, 2, 3]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest apps/bench/tests/test_bench_explain.py -v`
Expected: FAIL (`ModuleNotFoundError: bench.explain`)

- [ ] **Step 3: Implement**

```python
import numpy as np
import shap

from bench.models import FittedModel

_QS = (5, 25, 50, 75, 95)


def stratified_sample(y: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """Up to ``n`` rows: all positives (capped at n // 2) plus random negatives."""
    y = np.asarray(y).astype(int)
    if len(y) <= n:
        return np.arange(len(y))
    pos = np.flatnonzero(y == 1)
    neg = np.flatnonzero(y == 0)
    n_pos = min(len(pos), n // 2)
    pos_pick = rng.choice(pos, n_pos, replace=False) if n_pos < len(pos) else pos
    neg_pick = rng.choice(neg, min(len(neg), n - n_pos), replace=False)
    return np.sort(np.concatenate([pos_pick, neg_pick]))


def _positive_class(sv) -> np.ndarray:
    if isinstance(sv, list):
        return np.asarray(sv[-1])
    sv = np.asarray(sv)
    return sv[:, :, -1] if sv.ndim == 3 else sv


def _shap_values(model: FittedModel, x_train, x_explain, ann_rows, seed):
    xe = model.transform(x_explain)
    if model.kind in ("tree", "xgb"):
        sv = shap.TreeExplainer(model.estimator).shap_values(xe)
        return _positive_class(sv), "TreeExplainer", xe
    xt = model.transform(x_train)
    if model.kind == "linear":
        sv = shap.LinearExplainer(model.estimator, xt).shap_values(xe)
        return _positive_class(sv), "LinearExplainer", xe
    rng = np.random.default_rng(seed)
    xe = xe[rng.choice(len(xe), min(len(xe), ann_rows), replace=False)] if len(xe) > ann_rows else xe
    bg = shap.kmeans(xt, 10)
    explainer = shap.KernelExplainer(lambda a: model.estimator.predict_proba(a)[:, 1], bg)
    sv = explainer.shap_values(xe, nsamples=200, silent=True)
    return _positive_class(sv), "KernelExplainer", xe


def explain_model(
    model: FittedModel,
    x_train,
    x_explain,
    feature_names,
    *,
    ann_rows: int = 1000,
    seed: int = 0,
    max_points: int = 300,
) -> dict:
    sv, method, xe = _shap_values(model, np.asarray(x_train), np.asarray(x_explain), ann_rows, seed)
    sv = np.nan_to_num(np.asarray(sv, dtype="float64"), nan=0.0, posinf=0.0, neginf=0.0)
    # feature values for colouring are shown on the original (unscaled) scale, normalised 0..1
    raw = np.asarray(x_explain, dtype="float64")
    if len(raw) != len(sv):  # kernel path subsampled rows; align by recomputing the same pick
        rng = np.random.default_rng(seed)
        raw = raw[rng.choice(len(raw), len(sv), replace=False)]
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(sv), min(len(sv), max_points), replace=False)
    out = {"method": method, "n_rows": int(len(sv)), "importance": {}, "quantiles": {}, "points": {}}
    for j, name in enumerate(feature_names):
        col = sv[:, j]
        out["importance"][name] = float(np.mean(np.abs(col)))
        out["quantiles"][name] = [float(v) for v in np.percentile(col, _QS)]
        v = raw[:, j]
        lo, hi = float(v.min()), float(v.max())
        norm = (v - lo) / (hi - lo) if hi > lo else np.zeros_like(v)
        out["points"][name] = {
            "shap": col[pick].astype(float).tolist(),
            "value": norm[pick].astype(float).tolist(),
        }
    return out
```
Note on the kernel path: the row subsampling uses `np.random.default_rng(seed).choice(len(x), ann_rows, ...)` on the *same* length array in both places, so the feature values align with the SHAP rows. If the implementer finds this fragile, return the chosen row indices from `_shap_values` and use them directly (preferred; do it).

- [ ] **Step 4: Run to verify pass, lint**

Run: `uv run pytest apps/bench/tests/test_bench_explain.py -v && uv run ruff check apps/bench && uv run ruff format apps/bench`
Expected: all pass. shap API drift (list vs 3-D arrays for RF, `silent=` argument) is handled in `_positive_class`; fix minimally if a version differs.

- [ ] **Step 5: Commit**

```bash
git add apps/bench
git commit -m "feat(bench): shap importance and distribution extraction"
```

---

### Task 5: HTML report

**Files:**
- Create: `apps/bench/src/bench/report.py`
- Test: `apps/bench/tests/test_bench_report.py`

**Interfaces:**
- Consumes the `results` dict produced by Task 6:
  ```
  results = {
    "run": {"data_dir": str, "n_events": int, "n_features": int, "feature_names": [str],
            "split_sizes": {"train": int, "valid": int, "test": int},
            "bad_rate": float, "seed": int, "generated_at": str},
    "models": {name: {"display": str, "failed": str | None, "train_seconds": float,
                      "infer_seconds": float, "metrics": {...} | None,
                      "valid_metrics": {...} | None, "shap": {...} | None}}
  }
  ```
- Produces:
  - `to_jsonable(obj)`: recursively converts numpy types, NaN/inf -> `None`
  - `render_report(results: dict, *, lang: str = "zh") -> str`: self-contained HTML containing, per model present: summary table row, ROC and PR curve series, heatmap row, calibration, SHAP section. Failed models appear in a "failed" box.
  - `svg_lines(series, *, xlabel, ylabel, diagonal=False, baseline_y=None) -> str`

- [ ] **Step 1: Write the failing tests**

```python
import json
import math
import re

from bench.report import render_report, svg_lines, to_jsonable


def _metrics(auc):
    return {
        "n": 1000, "n_pos": 20, "auc": auc, "pr_auc": auc / 3, "recall_at_p50": 0.3,
        "recall_at_p80": 0.1, "precision_top_0_5pct": 0.5, "precision_top_1pct": 0.4,
        "lift_top_1pct": 20.0, "ks": 0.4, "log_loss": 0.2, "brier": 0.02,
        "roc_curve": {"fpr": [0, 0.5, 1], "tpr": [0, 0.8, 1]},
        "pr_curve": {"recall": [0, 0.5, 1], "precision": [1, 0.6, 0.02]},
        "calibration": [{"mean_pred": 0.01, "frac_pos": 0.012, "count": 500},
                        {"mean_pred": 0.2, "frac_pos": 0.15, "count": 500}],
        "confusion": {"threshold": 0.3, "tn": 900, "fp": 80, "fn": 5, "tp": 15,
                      "precision": 0.15, "recall": 0.75, "f1": 0.25},
    }


def _shap(top):
    feats = [top, "b", "c"]
    return {
        "method": "TreeExplainer", "n_rows": 100,
        "importance": {top: 1.0, "b": 0.3, "c": 0.01},
        "quantiles": {f: [-1, -0.5, 0, 0.5, 1] for f in feats},
        "points": {f: {"shap": [-1, 0, 1], "value": [0, 0.5, 1]} for f in feats},
    }


def _results():
    models = {}
    for name, auc in [("logreg", 0.7), ("rf", 0.8), ("xgb", 0.85), ("ann_small", 0.75)]:
        models[name] = {"display": name.upper(), "failed": None, "train_seconds": 1.0,
                        "infer_seconds": 0.1, "metrics": _metrics(auc),
                        "valid_metrics": _metrics(auc), "shap": _shap("amount")}
    models["ann_large"] = {"display": "ANN large", "failed": "RuntimeError: boom<script>",
                           "train_seconds": 0.0, "infer_seconds": 0.0, "metrics": None,
                           "valid_metrics": None, "shap": None}
    return {"run": {"data_dir": "data/x", "n_events": 1000, "n_features": 3,
                    "feature_names": ["amount", "b", "c"],
                    "split_sizes": {"train": 600, "valid": 200, "test": 200},
                    "bad_rate": 0.02, "seed": 0, "generated_at": "2026-10-14"},
            "models": models}


def test_report_contains_all_models_and_sections():
    html = render_report(_results(), lang="en")
    for token in ("LOGREG", "RF", "XGB", "ANN_SMALL", "ROC", "PR", "SHAP", "Calibration"):
        assert token in html
    assert html.count("<svg") >= 4
    assert "failed" in html.lower() and "amount" in html


def test_report_is_self_contained_and_escapes_text():
    html = render_report(_results(), lang="zh")
    assert not re.search(r"(src|href)=[\"']https?://", html)
    assert "<script src" not in html and "<link" not in html
    assert "&lt;script&gt;" in html and "boom<script>" not in html


def test_report_renders_with_nan_metrics_and_without_shap():
    r = _results()
    r["models"]["rf"]["metrics"].update(auc=float("nan"), pr_auc=float("nan"))
    r["models"]["xgb"]["shap"] = None
    html = render_report(r, lang="en")
    body = html.split("<body>")[1]
    assert "NaN" not in body and not re.search(r"\bnan\b", body.lower())


def test_to_jsonable_replaces_nonfinite_and_numpy():
    import numpy as np

    obj = {"a": float("nan"), "b": [np.float64(1.5), np.int64(3), float("inf")], "c": np.array([1, 2])}
    out = to_jsonable(obj)
    assert out == {"a": None, "b": [1.5, 3, None], "c": [1, 2]}
    json.dumps(out, allow_nan=False)


def test_svg_lines_is_well_formed():
    s = svg_lines(
        [{"name": "m", "color": "#2f6fed", "xs": [0, 1], "ys": [0, 1]}],
        xlabel="FPR", ylabel="TPR", diagonal=True,
    )
    assert s.startswith("<svg") and s.rstrip().endswith("</svg>") and "polyline" in s
    assert not math.isnan(len(s))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest apps/bench/tests/test_bench_report.py -v`
Expected: FAIL (`ModuleNotFoundError: bench.report`)

- [ ] **Step 3: Implement**

Create `bench/report.py` with these parts (self-contained, no template files):

1. `to_jsonable` (numpy scalars/arrays -> Python; any float not finite -> `None`; dict/list/tuple recursion).
2. `_esc = html.escape`; `_fmt(v, digits=3)` returns `"—"` for `None`/non-finite else formatted float.
3. `PALETTE = ["#2f6fed", "#e4572e", "#17a398", "#f2a900", "#8e44ad"]`; model colour assigned by order of `results["models"]`.
4. `svg_lines(series, *, xlabel, ylabel, diagonal=False, baseline_y=None, width=520, height=360)`: viewBox SVG with margins (l=52, r=14, t=14, b=46), axes in [0,1], ticks every 0.2 with light grid, one `<polyline>` per series (`stroke=color`, `fill=none`, `stroke-width=2`), optional dashed diagonal, optional dashed horizontal baseline, axis labels as `<text>`. Use CSS variables `var(--fg)`/`var(--line)` for text/grid so dark mode works.
5. `_legend(models)` HTML chips.
6. `_summary_table` (rows = models; columns AUC, PR-AUC, KS, recall@P0.5, recall@P0.8, P@top1%, lift@1%, log loss, Brier, train s, infer s); best value per column bold (lowest for log loss/Brier/times).
7. `_heatmap` HTML table with per-column min-max coloured cells via inline `background` (`hsl(210 70% {L}%)`).
8. `_calibration_svg`: x = mean_pred, y = frac_pos, one line per model, diagonal.
9. `_confusion_table` per model (tn/fp/fn/tp, precision, recall, F1, threshold).
10. `_shap_section`: (a) cross-model table: union of each model's top-8 features (by normalised importance = mean|shap| / sum over features), cells = normalised importance as a coloured bar/percent; (b) per model: horizontal bar SVG of top-12 normalised importances and a strip plot SVG (per feature row: dots at `shap` x-position coloured blue→red by `value`, plus a short line from q25 to q75 and a tick at q50). Models with `shap is None` show a "SHAP unavailable" note.
11. `LABELS = {"zh": {...}, "en": {...}}` for headings (Summary/汇总, ROC curves/ROC 曲线, PR curves/PR 曲线, Metrics/指标, Operating point/工作点, Calibration/校准, SHAP/SHAP 特征贡献, Run details/运行详情, Failed models/失败的模型).
12. `render_report(results, *, lang="zh") -> str`: assemble `<!DOCTYPE html>` with inline `<style>` (light/dark CSS variables like the af-tldr template), header with run facts, sections in the spec order. Every dynamic string goes through `_esc`. Failed models are listed in a `.callout.warn` box with their escaped error. If every model failed, still render a valid page.

All chart numbers come from `results`; do not invent data. The function must not read files or network.

- [ ] **Step 4: Run to verify pass, lint**

Run: `uv run pytest apps/bench/tests/test_bench_report.py -v && uv run ruff check apps/bench && uv run ruff format apps/bench`
Expected: 5 passed. Also open a rendered sample: write `render_report(_results())` to a scratch file and eyeball it once (`open <path>`).

- [ ] **Step 5: Commit**

```bash
git add apps/bench
git commit -m "feat(bench): self-contained SVG/HTML comparison report"
```

---

### Task 6: Orchestrator, CLI, docs and the 500k run

**Files:**
- Create: `apps/bench/src/bench/compare.py`
- Modify: `apps/bench/src/bench/cli.py`, `apps/bench/README.md`, root `README.md`
- Test: `apps/bench/tests/test_bench_compare.py`

**Interfaces:**
- Consumes: `load_events`, `time_split` (existing `bench.runner`), `build_features`/`feature_names`, `train_all`/`MODEL_ORDER`/`DISPLAY`, `compute_metrics`/`best_f1_threshold`, `explain_model`/`stratified_sample`, `render_report`/`to_jsonable`.
- Produces:
  - `run_compare(data_dir, *, models=MODEL_ORDER, shap_rows=5000, ann_shap_rows=1000, seed=0, min_train_pos=50) -> dict` (the `results` schema from Task 5; never reads `golden.parquet`)
  - `write_outputs(results, html_path, json_path=None, *, lang="zh") -> None`
  - CLI: `bench compare DATA_DIR --out report.html [--json metrics.json] [--models a,b] [--shap-rows N] [--ann-shap-rows N] [--seed S] [--lang zh|en]`

- [ ] **Step 1: Write the failing tests**

```python
import json
import re

import pytest
from datagen.cli import main as datagen_main

from bench.cli import main as bench_main
from bench.compare import run_compare, write_outputs


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("cmp")
    datagen_main(
        ["generate", "--scenario", "fraud", "--n-events", "8000", "--seed", "21",
         "--span-days", "60", "--out", str(out)]
    )
    return out


def test_run_compare_all_models(data_dir):
    r = run_compare(data_dir, shap_rows=400, ann_shap_rows=40, seed=0)
    assert set(r["models"]) == {"logreg", "rf", "xgb", "ann_small", "ann_large"}
    for name, m in r["models"].items():
        assert m["failed"] is None, (name, m["failed"])
        assert m["metrics"]["auc"] > 0.5
        assert m["shap"] and m["shap"]["importance"]
    assert r["run"]["n_events"] == 8000 and r["run"]["n_features"] > 10
    assert sum(r["run"]["split_sizes"].values()) == 8000


def test_golden_parquet_is_never_read(data_dir, monkeypatch):
    import polars as pl

    real = pl.read_parquet

    def guard(path, *a, **k):
        assert "golden" not in str(path)
        return real(path, *a, **k)

    monkeypatch.setattr(pl, "read_parquet", guard)
    run_compare(data_dir, models=("logreg",), shap_rows=200, seed=0)


def test_failed_model_does_not_kill_run(data_dir, monkeypatch):
    import bench.models as m

    monkeypatch.setitem(m._FACTORIES, "rf", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    r = run_compare(data_dir, models=("logreg", "rf"), shap_rows=200, seed=0)
    assert r["models"]["rf"]["failed"] and r["models"]["logreg"]["failed"] is None


def test_cli_writes_report_and_json(data_dir, tmp_path):
    html, js = tmp_path / "r.html", tmp_path / "m.json"
    rc = bench_main(
        ["compare", str(data_dir), "--out", str(html), "--json", str(js),
         "--models", "logreg,xgb", "--shap-rows", "300", "--lang", "en"]
    )
    assert rc == 0 and html.exists() and js.exists()
    page = html.read_text()
    assert "Logistic Regression" in page and "XGBoost" in page
    assert not re.search(r"(src|href)=[\"']https?://", page)
    data = json.loads(js.read_text())  # strict JSON: no NaN literals
    assert data["models"]["xgb"]["metrics"]["auc"] > 0.5


def test_single_class_labels_still_render(data_dir, tmp_path):
    import polars as pl

    d = tmp_path / "flat"
    d.mkdir()
    ev = pl.read_parquet(data_dir / "events.parquet").with_columns(label=pl.lit(0))
    ev.write_parquet(d / "events.parquet")
    (d / "meta.json").write_text((data_dir / "meta.json").read_text())
    r = run_compare(d, models=("logreg",), shap_rows=100, seed=0)
    assert r["models"]["logreg"]["failed"]
    write_outputs(r, tmp_path / "x.html", tmp_path / "x.json", lang="en")
    assert (tmp_path / "x.html").exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest apps/bench/tests/test_bench_compare.py -v`
Expected: FAIL (`ModuleNotFoundError: bench.compare`)

- [ ] **Step 3: Implement `compare.py`**

```python
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from bench.explain import explain_model, stratified_sample
from bench.features import build_features, feature_names
from bench.metrics import best_f1_threshold, compute_metrics
from bench.models import DISPLAY, MODEL_ORDER, FittedModel, train_all
from bench.report import render_report, to_jsonable
from bench.runner import load_events, time_split


def run_compare(
    data_dir,
    *,
    models=MODEL_ORDER,
    shap_rows: int = 5000,
    ann_shap_rows: int = 1000,
    seed: int = 0,
    min_train_pos: int = 50,
) -> dict:
    events, meta = load_events(data_dir)  # guards: label present, no golden leakage
    feats = build_features(events)
    names = feature_names(feats)
    df = events.select("event_id", "event_time", "label").join(
        feats, on="event_id", how="left", maintain_order="left"
    )
    tr, va, te = time_split(df)
    x = {k: v.select(names).to_numpy().astype("float64") for k, v in
         {"train": tr, "valid": va, "test": te}.items()}
    y = {k: v["label"].to_numpy().astype(int) for k, v in
         {"train": tr, "valid": va, "test": te}.items()}
    if y["train"].sum() < min_train_pos:
        print(f"warning: only {int(y['train'].sum())} positives in train (< {min_train_pos})")

    fitted = train_all(x["train"], y["train"], x["valid"], y["valid"], names=tuple(models), seed=seed)
    rng = np.random.default_rng(seed)
    sample_idx = stratified_sample(y["test"], shap_rows, rng)
    out_models: dict = {}
    for name, m in fitted.items():
        entry = {"display": DISPLAY[name], "failed": None, "train_seconds": 0.0,
                 "infer_seconds": 0.0, "metrics": None, "valid_metrics": None, "shap": None}
        if not isinstance(m, FittedModel):
            entry["failed"] = m.error
            out_models[name] = entry
            continue
        entry["train_seconds"] = float(m.train_seconds)
        t0 = time.perf_counter()
        p_valid = m.predict_proba(x["valid"])
        p_test = m.predict_proba(x["test"])
        entry["infer_seconds"] = float(time.perf_counter() - t0)
        thr = best_f1_threshold(y["valid"], p_valid)
        entry["valid_metrics"] = compute_metrics(y["valid"], p_valid, threshold=thr)
        entry["metrics"] = compute_metrics(y["test"], p_test, threshold=thr)
        try:
            entry["shap"] = explain_model(
                m, x["train"], x["test"][sample_idx], names, ann_rows=ann_shap_rows, seed=seed
            )
        except Exception as e:  # noqa: BLE001 - SHAP failure must not drop the model
            entry["shap"] = None
            entry["shap_error"] = f"{type(e).__name__}: {e}"
        out_models[name] = entry

    return {
        "run": {
            "data_dir": str(data_dir),
            "n_events": int(events.height),
            "n_features": len(names),
            "feature_names": names,
            "split_sizes": {"train": tr.height, "valid": va.height, "test": te.height},
            "bad_rate": float(events["label"].mean()),
            "seed": seed,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "dataset_meta": {k: meta.get(k) for k in ("scenario", "seed", "n_events", "bad_rate")},
        },
        "models": out_models,
    }


def write_outputs(results: dict, html_path, json_path=None, *, lang: str = "zh") -> None:
    Path(html_path).parent.mkdir(parents=True, exist_ok=True)
    Path(html_path).write_text(render_report(results, lang=lang), encoding="utf-8")
    if json_path:
        Path(json_path).write_text(
            json.dumps(to_jsonable(results), indent=2, allow_nan=False), encoding="utf-8"
        )
```
Note: `pl` import is only needed if used; drop unused imports before ruff.

- [ ] **Step 4: Add the CLI subcommand**

In `cli.py` add a `compare` subparser with the flags above (`--out` required, `--models` comma list validated against `MODEL_ORDER`, `--lang` choices `zh|en` default `zh`), call `run_compare` then `write_outputs`, print a short results table (model, AUC, PR-AUC, KS, train s) and the output path. Keep `run` unchanged.

- [ ] **Step 5: Run to verify pass, lint, full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, no warnings. If a statistical assertion (`auc > 0.5` for every model on 8k events) is flaky for a single model, raise `--n-events` in the fixture rather than lowering the assertion.

- [ ] **Step 6: Docs**

Update `apps/bench/README.md` and root `README.md`: add the `bench compare` usage, the five models and ANN sizes, the observable-feature list, that `golden.parquet` is not read, runtime expectations, and how to read the report sections.

- [ ] **Step 7: The real 500k run**

Run (data under the session scratchpad or `data/`, which is git-ignored):
```bash
uv run datagen generate --scenario fraud --n-events 500000 --seed 42 --out data/fraud500k
time uv run bench compare data/fraud500k --out reports/payment-risk-benchmark.html \
  --json reports/payment-risk-benchmark.json --lang zh
```
Expected: completes; the report lists five models with ROC/PR curves, SHAP, metrics. Record wall-clock time per stage (feature build, each model's train seconds, SHAP) in the commit message body or the task report. If SHAP on the ANNs dominates runtime (>15 min), lower `--ann-shap-rows`; do not remove SHAP. Add `reports/` to `.gitignore` (the report is an artifact, not source).

- [ ] **Step 8: Commit**

```bash
git add apps/bench README.md .gitignore
git commit -m "feat(bench): compare command, CLI and docs"
```
