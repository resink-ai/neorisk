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
    assert out["n_rows"] == (60 if name.startswith("ann") else 150)


def test_stratified_sample_keeps_positives_and_is_deterministic():
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


def test_ann_deterministic_with_many_features_and_aligned_points():
    rng = np.random.default_rng(3)
    x = rng.normal(size=(1500, 12))
    y = (rng.random(1500) < 1 / (1 + np.exp(-(2.5 * x[:, 0] - 1.0)))).astype(int)
    names = [f"f{i}" for i in range(12)]
    m = train_all(x[:1100], y[:1100], x[1100:], y[1100:], names=("ann_small",), seed=1)["ann_small"]
    kw = {"ann_rows": 50, "seed": 4}
    a = explain_model(m, x[:1100], x[1100:], names, **kw)
    b = explain_model(m, x[:1100], x[1100:], names, **kw)
    assert a == b
    assert a["n_rows"] == 50
    p = a["points"]["f0"]
    assert np.corrcoef(p["shap"], p["value"])[0, 1] > 0.8


@pytest.mark.parametrize(
    ("name", "method", "unit"),
    [
        ("logreg", "LinearExplainer", "log-odds"),
        ("rf", "TreeExplainer", "probability"),
        ("xgb", "TreeExplainer", "log-odds"),
        ("ann_small", "KernelExplainer", "probability"),
    ],
)
def test_explain_result_carries_method_and_unit(fitted, name, method, unit):
    res, x, _ = fitted
    out = explain_model(res[name], x[:1800], x[1800:1900], NAMES, ann_rows=20, seed=0)
    assert out["method"] == method and out["unit"] == unit
