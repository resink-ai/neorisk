from itertools import combinations

import numpy as np
import torch

from devicefp import pairs as pp
from devicefp.v2 import average_precision, roc_auc
from devicefp.v3 import FS, agreement, agreement_matrix, bcubed, components_split, env_target


def _brute_strata(tmx, spec, env):
    counts = dict.fromkeys(pp.STRATA, 0)
    for a, b in combinations(range(len(tmx)), 2):
        counts[pp.STRATA[pp.stratum_of(np.array([a]), np.array([b]), tmx, spec, env)[0]]] += 1
    return counts


def test_strata_counts_match_brute_force():
    rng = np.random.default_rng(0)
    tmx = rng.integers(0, 15, 60)
    spec = np.where(rng.random(60) < 0.2, -1, rng.integers(0, 5, 60))
    env = np.where(rng.random(60) < 0.3, -1, rng.integers(0, 8, 60))
    assert pp.strata_counts(tmx, spec, env) == _brute_strata(tmx, spec, env)


def test_build_pairs_respects_strata_and_weights_sum_to_population():
    rng = np.random.default_rng(1)
    n = 400
    tmx, spec = rng.integers(0, 120, n), rng.integers(0, 10, n)
    env = np.where(rng.random(n) < 0.3, -1, rng.integers(0, 30, n))
    rows = np.arange(0, n, 2)  # only even rows belong to this split
    ps, counts = pp.build_pairs(rows, tmx, spec, env, 0, {"pos": 500, "spec": 500, "env": 500, "rest": 500}, seed=0)
    assert np.isin(ps.a, rows).all() and np.isin(ps.b, rows).all() and (ps.a != ps.b).all()
    assert (pp.stratum_of(ps.a, ps.b, tmx, spec, env) == ps.stratum).all()
    assert np.isclose(ps.w.sum(), len(rows) * (len(rows) - 1) // 2)
    for i, name in enumerate(pp.STRATA):
        assert np.isclose(ps.w[ps.stratum == i].sum(), counts[name])


def test_weighted_metrics_reduce_to_unweighted():
    rng = np.random.default_rng(2)
    s, y = rng.random(2000), (rng.random(2000) < 0.3).astype(np.int64)
    one = np.ones(2000)
    assert np.isclose(pp.weighted_ap(s, y, one), average_precision(s, y))
    assert np.isclose(pp.weighted_auc(s, y, one), roc_auc(s, y))
    # duplicating a sample n times is the same as giving it weight n
    w = rng.integers(1, 4, 2000).astype(float)
    s2, y2 = np.repeat(s, w.astype(int)), np.repeat(y, w.astype(int))
    assert np.isclose(pp.weighted_auc(s, y, w), roc_auc(s2, y2))
    assert np.isclose(pp.weighted_ap(s, y, w), pp.weighted_ap(s2, y2, np.ones(len(s2))))
    assert np.isclose(pp.weighted_ap(s2, y2, np.ones(len(s2))), _tied_ap(s2, y2))


def _tied_ap(s, y):
    ap, prev_r = 0.0, 0.0
    for t in np.unique(s)[::-1]:
        pred = s >= t
        p, r = y[pred].mean(), y[pred].sum() / y.sum()
        ap += (r - prev_r) * p
        prev_r = r
    return ap


def test_components_split_keeps_linked_rows_together():
    tmx = np.array([0, 0, 1, 2, 3, 3, 4])
    dev = np.array([-1, 5, 5, -1, -1, -1, 6])
    comp, split = components_split(7, [tmx, dev])
    assert comp[0] == comp[1] == comp[2] and comp[4] == comp[5]
    assert len({comp[3], comp[0], comp[4], comp[6]}) == 4
    for c in np.unique(comp):
        assert len(np.unique(split[comp == c])) == 1


def test_fs_rewards_rare_agreement_more_than_common():
    raw = np.array([[0], [0], [1], [1], [0], [0], [0], [0], [0], [0]], dtype=np.int32)
    devid = np.array([0, 0, 1, 1, 2, 3, 4, 5, 6, 7])
    fs = FS.fit(raw, devid, np.arange(10), pairs=1000)
    s = fs.score(raw, np.array([2, 0]), np.array([3, 1]))  # agree on rare value 1 vs common value 0
    assert s[0] > s[1]


def test_agreement_matches_batch_version_and_ignores_missing():
    raw = np.array([[1, 2, -1], [1, 3, 4], [1, 2, 4]], dtype=np.int32)
    w = np.array([1.0, 2.0, 1.0])
    a, b = np.array([0, 1, 0]), np.array([1, 2, 2])
    t = agreement(raw, w, a, b)
    assert np.allclose(t, [1 / 3, 2 / 4, 3 / 3])
    tm, ok = agreement_matrix(torch.from_numpy(raw), torch.from_numpy(w).float())
    assert np.allclose(tm.numpy()[a, b], t) and ok.all()


def test_env_target_takes_the_strongest_shared_key():
    lab = {"bssid": np.array([7, 7, -1]), "net": np.array([1, 2, 2]), "subnet": np.array([3, 3, 3]), "city": np.array([9, 9, 9])}
    t = env_target(lab, np.arange(3))
    assert t[0, 1] == 1.0 and t[1, 2] == 0.5 and t[0, 2] == 0.15


def test_bcubed_perfect_and_merged():
    truth = np.array([0, 0, 1, 1])
    assert bcubed(truth.copy(), truth) == (1.0, 1.0)
    p, r = bcubed(np.zeros(4, dtype=int), truth)
    assert p == 0.5 and r == 1.0
