"""Metrics on a 10-user case worked out by hand."""

import numpy as np
import pytest

from bench.discover.metrics import aggregate, summarize
from bench.discover.protocol import Trace
from bench.discover.world import Truth

IDS = np.arange(10, dtype=np.int64) + 100


def _case():
    bad = np.zeros(10, bool)
    bad[:4] = True
    stealth = np.zeros(10, bool)
    stealth[3] = True
    cohort = np.array(["ring"] * 4 + ["promoter", "promoted_friend"] + ["base"] * 4)
    truth = Truth(bad=bad, stealth=stealth, cohort=cohort,
                  available_at=np.full(10, np.datetime64("NaT", "us")))
    scores = np.zeros(10)
    scores[[3, 5, 7, 8, 9]] = [0.9, 0.95, 0.1, 0.2, 0.3]
    t = Trace("m", seeds=[100], reviewed=[[101, 104], [102, 106]], hits=[1, 1],
              known={100: 1, 101: 1, 104: 0, 102: 1, 106: 0}, scores=scores)
    return t, truth


def test_summary_matches_the_hand_computed_values():
    t, truth = _case()
    s = summarize(t, IDS, truth, block_shares=[0.4])
    assert s["found"] == [1, 2] and s["hit_rate"] == [0.5, 0.5]
    assert s["recall_at_budget"] == pytest.approx(2 / 3)
    assert s["auc"] == pytest.approx(0.75) and s["pr_auc"] == pytest.approx(0.5)
    assert s["precision"] == pytest.approx(0.75) and s["recall"] == pytest.approx(0.75)
    assert s["stealth_recall"] == 0.0 and s["visible_recall"] == 1.0
    assert s["false_alarm"] == {"base": 0.0, "promoter": 0.0, "promoted_friend": 1.0}
    assert s["risk"] == [[pytest.approx(0.6), pytest.approx(1 / 6)]]
    assert len(s["roc"]) >= 2 and len(s["pr"]) >= 2


def test_aggregate_gives_mean_and_spread_across_seed_draws():
    a = aggregate([{"auc": 0.5, "found": [1, 2]}, {"auc": 0.7, "found": [3, 4]}])
    assert a["auc"]["mean"] == pytest.approx(0.6) and a["auc"]["sd"] == pytest.approx(0.1)
    assert a["found"]["mean"] == [2, 3]


def test_aggregate_averages_risk_points():
    a = aggregate([{"risk": [[0.9, 0.02]]}, {"risk": [[0.9, 0.04]]}])
    assert a["risk"]["mean"] == [[0.9, pytest.approx(0.03)]]
