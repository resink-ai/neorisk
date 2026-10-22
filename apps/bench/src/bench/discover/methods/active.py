"""The automated analyst: retrain a model on every review so far, review its top picks."""

from __future__ import annotations

import numpy as np
from xgboost import XGBClassifier

from bench.discover.features import standardize, user_matrix
from bench.discover.methods.behaviour import split
from bench.discover.methods.graph import ALPHA, device_graph, known_bad, money_graph, ppr
from bench.discover.methods.weak import votes
from bench.discover.protocol import Ranker
from bench.discover.world import World

# frozen defaults: set before the first scored run, never tuned on truth
TREES = 100
DEPTH = 4
SOFT_NEG_RATIO = 20           # unlabeled users as soft negatives per known bad
SOFT_NEG_WEIGHT = 0.2
MIN_CHILD_WEIGHT = 0.05       # a handful of seeds must still be able to split a node


class Active(Ranker):
    key = "active"

    def __init__(self, seed: int):
        self.seed = seed
        self._round = 0

    def features(self, world: World, known: dict[int, int]) -> np.ndarray:
        start = known_bad(world, known)
        n = len(world.user_ids)
        # without each seed's own restart mass, which would let the model memorise the seeds
        s = start / max(start.sum(), 1)
        graph = np.column_stack([(ppr(device_graph(world), start) - ALPHA * s) * n,
                                 (ppr(money_graph(world), start) - ALPHA * s) * n])
        v = votes(world)
        return np.column_stack([standardize(user_matrix(world)[0]), graph,
                                (v == 1).sum(axis=1), (v == 0).sum(axis=1)])

    def score(self, world: World, known: dict[int, int]) -> np.ndarray:
        self._round += 1
        x = self.features(world, known)
        bad, good = split(world, known)
        rng = np.random.default_rng([self.seed, self._round])
        free = np.setdiff1d(np.arange(len(x)), np.concatenate([bad, good]))
        soft = rng.choice(free, size=min(len(free), SOFT_NEG_RATIO * len(bad)), replace=False)
        rows = np.concatenate([bad, good, soft])
        y = np.concatenate([np.ones(len(bad)), np.zeros(len(good) + len(soft))])
        w = np.concatenate([np.ones(len(bad) + len(good)), np.full(len(soft), SOFT_NEG_WEIGHT)])
        m = XGBClassifier(n_estimators=TREES, max_depth=DEPTH, learning_rate=0.1,
                          min_child_weight=MIN_CHILD_WEIGHT, random_state=self.seed,
                          n_jobs=4, verbosity=0)
        m.fit(x[rows], y, sample_weight=w)
        return m.predict_proba(x)[:, 1]
