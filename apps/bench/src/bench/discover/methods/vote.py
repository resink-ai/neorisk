"""Agreement: how many member methods place a user near their top."""

from __future__ import annotations

import numpy as np

from bench.discover.methods.behaviour import Similarity, Sync
from bench.discover.methods.graph import Connection, MoneyFlow
from bench.discover.methods.weak import Rules
from bench.discover.protocol import Ranker
from bench.discover.world import World

# frozen defaults: set before the first scored run, never tuned on truth
TOP_SHARE = 0.02


def _rank_pct(s: np.ndarray) -> np.ndarray:
    return np.argsort(np.argsort(s, kind="stable"), kind="stable") / max(len(s) - 1, 1)


class Vote(Ranker):
    key = "vote"

    def __init__(self, seed: int):
        self.seed = seed
        self.members = [Connection(seed), MoneyFlow(seed), Similarity(seed), Sync(seed),
                        Rules(seed)]

    def score(self, world: World, known: dict[int, int]) -> np.ndarray:
        pct = np.array([_rank_pct(m.score(world, known)) for m in self.members])
        top = (pct >= 1 - TOP_SHARE).sum(axis=0)
        return top + pct.mean(axis=0)                     # ties: the average rank
