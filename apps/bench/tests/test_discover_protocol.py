"""Seeds, the budgeted oracle and the round loop; the random and perfect baselines."""

import ast
from pathlib import Path

import numpy as np
import pytest

from bench.discover.methods import METHODS, make
from bench.discover.protocol import Oracle, draw_seeds, run_method

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
