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


def test_report_axes_label_only_values_they_reach():
    from bench.discover.report import Plot
    svg = Plot(0, 10, 0, 1, xticks=[0, 2, 5, 10]).svg()
    assert ">5</text>" in svg and ">8</text>" not in svg and ">2.5" not in svg
    small = Plot(0.9, 1, 0, 0.02, pct=True).svg()
    assert ">0.5%</text>" in small and ">1.0%</text>" in small


def test_summary_does_not_depend_on_user_row_order():
    t, truth = _case()
    t.scores[[7, 8, 9]] = 0.0                    # ties among unreviewed good users
    t.scores[[3, 5]] = 0.0                       # every unreviewed user ties
    perm = np.array([9, 3, 7, 0, 5, 1, 8, 2, 6, 4])
    pt = Truth(bad=truth.bad[perm], stealth=truth.stealth[perm], cohort=truth.cohort[perm],
               available_at=truth.available_at[perm])
    t2 = Trace("m", t.seeds, t.reviewed, t.hits, t.known, t.scores[perm])
    a = summarize(t, IDS, truth, block_shares=[0.4, 0.6])
    b = summarize(t2, IDS[perm], pt, block_shares=[0.4, 0.6])
    for k in ("precision", "recall", "stealth_recall", "risk", "false_alarm", "auc"):
        assert a[k] == b[k], k


def test_label_set_is_the_known_bad_then_the_top_unreviewed():
    from bench.discover.metrics import label_set
    t, _ = _case()
    chosen = label_set(t, IDS, 4)
    assert set(IDS[chosen]) == {100, 101, 102, 105}          # 3 known bad, then 105 (0.95)


def test_reason_precision_counts_unreviewed_picks_that_carry_the_seeds_anomaly():
    from bench.discover.metrics import reason_precision
    t, _ = _case()
    carries = np.zeros(10, bool)
    carries[[3]] = True
    assert reason_precision(t, IDS, 4, carries) == 0.0        # the one pick, 105, does not
    assert reason_precision(t, IDS, 5, carries) == 0.5        # then 103 (0.9), which does


def test_summary_counts_the_reviewers_wrong_verdicts():
    t, truth = _case()
    assert summarize(t, IDS, truth)["wrong_labels"] == 0
    t.wrong = [1, 2]
    assert summarize(t, IDS, truth)["wrong_labels"] == 3
