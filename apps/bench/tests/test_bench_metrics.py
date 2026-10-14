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


def test_top_k_ties_use_expected_value_regardless_of_row_order():
    pos_last = np.array([0] * 950 + [1] * 50)
    for y in (pos_last, pos_last[::-1].copy()):
        m = compute_metrics(y, np.full(1000, 0.3))
        assert m["precision_top_1pct"] == pytest.approx(0.05)
        assert m["precision_top_0_5pct"] == pytest.approx(0.05)
        assert m["lift_top_1pct"] == pytest.approx(1.0)


def test_top_k_large_tied_block_at_cutoff_and_permutation_invariant():
    rng = np.random.default_rng(3)
    n = 2000
    p = np.concatenate([np.full(5, 0.99), np.full(1000, 0.5), np.full(995, 0.1)])
    y = (rng.random(n) < 0.1).astype(int)
    y[:5] = 1
    m = compute_metrics(y, p)
    base_tied = y[5:1005].mean()
    k = 20
    assert m["precision_top_1pct"] == pytest.approx((5 + (k - 5) * base_tied) / k)
    perm = rng.permutation(n)
    m2 = compute_metrics(y[perm], p[perm])
    for key in ("precision_top_0_5pct", "precision_top_1pct", "lift_top_1pct"):
        assert m2[key] == pytest.approx(m[key])


def test_binary_scores_give_finite_log_loss_and_two_calibration_bins():
    y = np.array([0, 0, 0, 1, 1, 0, 1, 0])
    p = y.astype(float)
    m = compute_metrics(y, p)
    assert math.isfinite(m["log_loss"])
    assert len(m["calibration"]) == 2
    assert sum(b["count"] for b in m["calibration"]) == len(y)
