"""Explaining a confirmed bad user by its anomalies, on the toy world and a simulated one."""

import numpy as np
import pytest
from discover_toy import ring_mask, toy_world

from bench.discover.explain import SIGNALS, anomaly_profile, explain, reason_score, tail_excess

pytest_plugins = ["discover_fixture"]

SEED = 27


def test_tail_excess_is_zero_for_common_values_and_grows_in_the_tail():
    raw = np.array([[0.0]] * 90 + [[1.0]] * 8 + [[5.0]] * 2)
    e = tail_excess(raw)[:, 0]
    assert (e[:90] == 0).all()                                  # 100% share: nothing
    assert 0 < e[90] < e[99]                                    # 10% share < 2% share
    assert e[99] == pytest.approx(np.log(0.2 / 0.02))


@pytest.mark.parametrize("probe", [False, True])
def test_profile_has_one_finite_nonnegative_row_per_user(probe):
    w = toy_world(probe)
    e = anomaly_profile(w)
    assert e.shape == (len(w.user_ids), len(SIGNALS))
    assert np.isfinite(e).all() and (e >= 0).all()


def test_a_zombie_is_explained_by_its_qualifying_trick_and_a_shopper_is_not():
    w = toy_world()
    ex = explain(w, {SEED: 1})
    assert {"near_min_share", "cheapest_share"} <= set(ex.reasons[SEED])
    shopper = int(np.flatnonzero(w.user_ids == 20)[0])
    assert anomaly_profile(w)[shopper].sum() == 0


def test_failed_checks_explain_a_probing_seed():
    w = toy_world(probe=True)
    names = [n for n, _ in explain(w, {SEED: 1}).top(20)]
    assert "fails:device_limit" in names and "fails:id_mismatch" not in names


def test_reviewed_good_users_cancel_the_anomalies_they_share():
    w = toy_world()
    alone = explain(w, {1: 1}).weights                          # the inviting shopper
    j = SIGNALS.index("invites_sent")
    assert alone[j] > 0
    assert explain(w, {1: 1, 2: 0, 26: 0}).weights[j] < alone[j]


def test_reason_score_puts_the_rest_of_the_ring_above_every_shopper():
    w = toy_world()
    s = reason_score(w, {SEED: 1})
    others = ring_mask(w) & (w.user_ids != SEED)
    assert s[others].min() > s[~ring_mask(w)].max()


def test_ring_members_carry_more_anomaly_than_everyone_else(probe_world_truth):
    world, truth = probe_world_truth
    total = anomaly_profile(world).sum(axis=1)
    assert np.median(total[truth.bad]) > 3 * max(np.median(total[~truth.bad]), 0.1)
