"""Each discovery method on a hand-built ring, and every method on a simulated world."""

import numpy as np
import pytest
from discover_toy import RING, ring_mask, toy_world

from bench.discover.features import NAMES, user_matrix
from bench.discover.methods import ORDER, make
from bench.discover.methods.weak import LF_NAMES, dawid_skene, votes
from bench.discover.protocol import draw_seeds

pytest_plugins = ["discover_fixture"]

SEED = 27                                             # one reported zombie
FINDS_THE_TOY_RING = ["connection", "money_flow", "sync", "rules", "label_model", "vote"]
FINDS_THE_LOOK_ALIKES = ["similarity", "pu_learn", "active"]      # zombies, not the hunter


@pytest.fixture(scope="module")
def toy():
    return toy_world()


def test_behaviour_vector_has_one_finite_row_per_user(toy, world_truth):
    for world in (toy, world_truth[0]):
        x, names = user_matrix(world)
        assert names == NAMES and x.shape == (len(world.user_ids), len(NAMES))
        assert np.isfinite(x).all()


@pytest.mark.parametrize("key", FINDS_THE_TOY_RING)
def test_method_ranks_the_rest_of_the_ring_above_every_shopper(toy, key):
    s = make(key, 0).score(toy, {SEED: 1})
    ring = ring_mask(toy) & (toy.user_ids != SEED)
    shoppers = ~ring_mask(toy)
    assert s[ring].min() > s[shoppers].max(), key


@pytest.mark.parametrize("key", FINDS_THE_LOOK_ALIKES)
def test_behaviour_method_ranks_the_other_zombies_above_every_shopper(toy, key):
    s = make(key, 0).score(toy, {SEED: 1})
    zombies = np.isin(toy.user_ids, [z for z in RING[1:] if z != SEED])
    assert s[zombies].min() > s[~ring_mask(toy)].max(), key


def test_labeling_functions_fire_on_the_ring_and_stay_quiet_on_shoppers(toy):
    v = votes(toy)
    assert v.shape == (len(toy.user_ids), len(LF_NAMES))
    assert ((v == 1).sum(axis=1)[ring_mask(toy)] >= 1).all()
    assert ((v == 1).sum(axis=1)[~ring_mask(toy)] == 0).all()


def test_label_model_respects_clamped_labels():
    v = np.array([[1, -1], [1, 1], [0, -1], [-1, 0], [-1, -1]])
    p = dawid_skene(v, {0: 1.0, 4: 0.0})
    assert p[0] == 1.0 and p[4] == 0.0
    assert p[1] > p[2] and p[1] > p[3]


@pytest.mark.parametrize("key", [k for k in ORDER if k != "perfect"])
def test_every_method_scores_and_proposes_on_a_simulated_world(world_truth, key):
    world, truth = world_truth
    seeds = draw_seeds(truth, world, 5, t_report_days=40, rng=np.random.default_rng(0))
    m = make(key, 0)
    known = {s: 1 for s in seeds}
    s = m.score(world, known)
    assert s.shape == (len(world.user_ids),) and np.isfinite(s).all()
    p = m.propose(world, known, 10)
    assert len(p) == 10 and not set(p) & set(seeds)
    assert m.score(world, known).shape == s.shape            # deterministic shape across rounds
