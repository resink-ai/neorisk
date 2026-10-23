"""Seeds, the budgeted oracle and the round loop; the random and perfect baselines."""

import ast
from pathlib import Path

import numpy as np
import pytest

from bench.discover.methods import METHODS, make
from bench.discover.protocol import REVIEWERS, Oracle, Reviewer, draw_seeds, run_method

pytest_plugins = ["discover_fixture"]
METHODS_DIR = Path(__file__).resolve().parents[1] / "src" / "bench" / "discover" / "methods"


def test_seeds_are_visible_bad_users_known_by_the_report_day(world_truth):
    world, truth = world_truth
    seeds = draw_seeds(truth, world, 5, t_report_days=40, rng=np.random.default_rng(0))
    idx = world.index(seeds)
    assert len(set(seeds)) == 5
    assert truth.bad[idx].all() and not truth.stealth[idx].any()
    start = world.users["created_at"].min().replace(tzinfo=None)
    limit = np.datetime64(start, "us") + np.timedelta64(40, "D")
    assert (truth.available_at[idx] <= limit).all()


def test_too_few_seed_candidates_is_an_error(world_truth):
    world, truth = world_truth
    with pytest.raises(ValueError, match="seed candidates"):
        draw_seeds(truth, world, 5, t_report_days=0.01, rng=np.random.default_rng(0))


def test_oracle_charges_only_new_known_ids(world_truth):
    world, truth = world_truth
    o = Oracle(truth, world, budget=3)
    a, b = (int(x) for x in world.user_ids[:2])
    assert set(o.review([a, b])) == {a, b} and o.spent == 2
    assert o.review([a, -1]) == {} and o.spent == 2           # repeat and unknown are free
    assert len(o.review([int(x) for x in world.user_ids[2:6]])) == 1 and o.spent == 3


def _everyone(world):
    return [int(x) for x in world.user_ids]


def test_the_default_reviewer_is_perfect(world_truth):
    world, truth = world_truth
    o = Oracle(truth, world, budget=len(world.user_ids))
    got = o.review(_everyone(world))
    assert np.array_equal(np.array([got[i] for i in _everyone(world)]), truth.bad.astype(int))
    assert REVIEWERS["perfect"] == Reviewer()


def test_an_imperfect_reviewer_misses_stealth_members_more_and_flags_promoters(world_truth):
    world, truth = world_truth
    r = Reviewer(miss=0.1, stealth_miss=0.5)
    o = Oracle(truth, world, budget=len(world.user_ids), reviewer=r, seed=7)
    got = o.review(_everyone(world))
    said = np.array([got[i] for i in _everyone(world)])
    st, vis = truth.bad & truth.stealth, truth.bad & ~truth.stealth
    assert abs((said[st] == 0).mean() - 0.5) < 0.1
    assert abs((said[vis] == 0).mean() - 0.1) < 0.05
    assert said[(truth.cohort == "base") & ~truth.bad].sum() == 0
    every = Oracle(truth, world, budget=len(world.user_ids), seed=7,
                   reviewer=Reviewer(promoter_false_alarm=1.0)).review(_everyone(world))
    flagged = {i for i, v in every.items() if v} - set(world.user_ids[truth.bad].tolist())
    assert flagged == set(world.user_ids[truth.cohort == "promoter"].tolist()) != set()


def test_a_reviewers_verdict_on_a_user_does_not_depend_on_review_order(world_truth):
    world, truth = world_truth
    r = REVIEWERS["noisy"]
    ids = _everyone(world)
    a = Oracle(truth, world, budget=len(ids), reviewer=r, seed=3).review(ids)
    b = Oracle(truth, world, budget=len(ids), reviewer=r, seed=3).review(ids[::-1])
    assert a == b
    c = Oracle(truth, world, budget=len(ids), reviewer=r, seed=4).review(ids)
    assert a != c


def test_hits_count_truly_bad_users_and_the_trace_counts_wrong_labels(world_truth):
    world, truth = world_truth
    seeds = draw_seeds(truth, world, 5, t_report_days=40, rng=np.random.default_rng(1))
    blind = Reviewer(miss=1.0, stealth_miss=1.0)
    t = run_method(make("perfect", 0, truth), world, truth, seeds=seeds, k=10, rounds=3,
                   reviewer=blind)
    assert t.hits == [10, 10, 10] and t.wrong == [10, 10, 10]
    assert all(t.known[i] == 0 for r in t.reviewed for i in r)
    assert all(t.known[s] == 1 for s in seeds)                 # reports are not reviewed
    ok = run_method(make("perfect", 0, truth), world, truth, seeds=seeds, k=10, rounds=3)
    assert ok.wrong == [0, 0, 0]


def test_perfect_finds_a_bad_user_with_every_review_and_random_rarely(world_truth):
    world, truth = world_truth
    seeds = draw_seeds(truth, world, 5, t_report_days=40, rng=np.random.default_rng(1))
    perfect = run_method(make("perfect", 0, truth), world, truth, seeds=seeds, k=10, rounds=3)
    assert perfect.hits == [10, 10, 10]
    rand = run_method(make("random", 0, truth), world, truth, seeds=seeds, k=10, rounds=3)
    assert sum(rand.hits) <= 5
    assert len(rand.scores) == len(world.user_ids)
    reviewed = [i for r in rand.reviewed for i in r]
    assert len(set(reviewed)) == 30 and not set(reviewed) & set(seeds)


def test_zero_rounds_is_one_shot_scoring(world_truth):
    world, truth = world_truth
    seeds = draw_seeds(truth, world, 5, t_report_days=40, rng=np.random.default_rng(1))
    t = run_method(make("random", 0, truth), world, truth, seeds=seeds, k=10, rounds=0)
    assert t.reviewed == [] and t.hits == [] and len(t.scores) == len(world.user_ids)


def test_methods_never_import_truth():
    allowed = {"baseline.py", "__init__.py"}     # perfect, and the registry that hands it truth
    for f in METHODS_DIR.glob("*.py"):
        if f.name in allowed:
            continue
        tree = ast.parse(f.read_text())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        assert "Truth" not in names and "truth" not in names, f.name


def test_every_registered_method_builds():
    assert {"random", "perfect"} <= set(METHODS)


def test_checkpoints_snapshot_the_trace_at_earlier_budgets(world_truth):
    world, truth = world_truth
    seeds = draw_seeds(truth, world, 5, t_report_days=40, rng=np.random.default_rng(1))
    t = run_method(make("perfect", 0, truth), world, truth, seeds=seeds, k=10, rounds=3,
                   checkpoints=(0, 2))
    assert set(t.snapshots) == {0, 2}
    assert t.snapshots[0].hits == [] and len(t.snapshots[0].known) == 5
    assert t.snapshots[2].hits == [10, 10] and len(t.snapshots[2].known) == 25


@pytest.mark.parametrize("key", ["random", "pu_learn", "active"])
def test_a_snapshot_equals_a_separate_shorter_run(world_truth, key):
    world, truth = world_truth
    seeds = draw_seeds(truth, world, 5, t_report_days=40, rng=np.random.default_rng(1))
    long = run_method(make(key, 0, truth), world, truth, seeds=seeds, k=10, rounds=3,
                      checkpoints=(0, 2))
    short = run_method(make(key, 0, truth), world, truth, seeds=seeds, k=10, rounds=2)
    plain = run_method(make(key, 0, truth), world, truth, seeds=seeds, k=10, rounds=3)
    assert long.snapshots[2].reviewed == short.reviewed
    assert np.array_equal(long.snapshots[2].scores, short.scores)
    assert long.reviewed == plain.reviewed and np.array_equal(long.scores, plain.scores)


def test_caches_live_on_the_world_they_describe():
    from discover_toy import toy_world

    from bench.discover.features import user_matrix
    w = toy_world()
    user_matrix(w)
    assert "features" in w.cache
    assert toy_world().cache == {}
