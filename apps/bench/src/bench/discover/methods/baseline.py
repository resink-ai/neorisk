"""The floor and the ceiling: review at random, or by the hidden truth."""

from __future__ import annotations

import numpy as np

from bench.discover.protocol import Ranker
from bench.discover.world import Truth, World


class Random(Ranker):
    key = "random"

    def __init__(self, seed: int):
        self.seed = seed
        self._round = 0

    def score(self, world: World, known: dict[int, int]) -> np.ndarray:
        self._round += 1
        return np.random.default_rng([self.seed, self._round]).random(len(world.user_ids))


class Perfect(Ranker):
    """The one method allowed to read truth: the ceiling every other curve is drawn against."""

    key = "perfect"

    def __init__(self, truth: Truth):
        self.truth = truth

    def score(self, world: World, known: dict[int, int]) -> np.ndarray:
        return self.truth.bad.astype(float)
