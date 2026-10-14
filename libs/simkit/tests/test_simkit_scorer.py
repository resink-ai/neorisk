import numpy as np
import polars as pl

from neorisk_simkit.scorer import MLPScorer, XGBScorer, calibrate, sample_labels


def _golden(n=2000, seed=0):
    rng = np.random.default_rng(seed)
    return pl.DataFrame(
        {
            "a": rng.normal(size=n),
            "b": rng.normal(size=n),
            "const": np.full(n, 3.0),  # zero variance
        }
    )


def test_xgb_scorer_deterministic_and_bounded():
    g = _golden()
    s1 = XGBScorer({"a": 2.0, "b": 0.5, "const": 1.0}, seed=1).score(g)
    s2 = XGBScorer({"a": 2.0, "b": 0.5, "const": 1.0}, seed=1).score(g)
    assert np.array_equal(s1, s2)
    assert np.isfinite(s1).all() and s1.min() > 0 and s1.max() < 1


def test_xgb_scorer_follows_weights():
    g = _golden()
    p = XGBScorer({"a": 3.0, "b": 0.0}, seed=0).score(g)
    corr_a = np.corrcoef(p, g["a"].to_numpy())[0, 1]
    corr_b = np.corrcoef(p, g["b"].to_numpy())[0, 1]
    assert corr_a > 0.8 and abs(corr_b) < 0.2


def test_mlp_scorer_deterministic_and_zero_variance_safe():
    g = _golden()
    p1 = MLPScorer(["a", "b", "const"], seed=2).score(g)
    p2 = MLPScorer(["a", "b", "const"], seed=2).score(g)
    assert np.array_equal(p1, p2) and np.isfinite(p1).all()
    assert 0 < p1.min() and p1.max() < 1


def test_calibrate_hits_target_rate():
    p = np.random.default_rng(0).beta(2, 8, size=10_000)
    for target in (0.01, 0.02, 0.2):
        assert abs(calibrate(p, target).mean() - target) < 1e-3


def test_sample_labels_rate():
    rng = np.random.default_rng(0)
    y = sample_labels(np.full(50_000, 0.02), rng)
    assert set(np.unique(y)) <= {0, 1} and 0.017 < y.mean() < 0.023
