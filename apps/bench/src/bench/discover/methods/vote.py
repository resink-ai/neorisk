"""Agreement: how many member methods place a user near their top.

`vote` pools the methods anchored on the seeds' anomalies; `vote_plain` the original five."""

from __future__ import annotations

import numpy as np
from scipy.stats import rankdata

from bench.discover.methods.behaviour import Similarity, Sync
from bench.discover.methods.graph import Connection, MoneyFlow
from bench.discover.methods.weak import Rules
from bench.discover.protocol import Ranker
from bench.discover.world import World

# frozen defaults: set before the first scored run, never tuned on truth
TOP_SHARE = 0.02


def rank_pct(s: np.ndarray) -> np.ndarray:
    """Rank as a share of the population; tied scores share their average rank (never the row
    order, which follows sign-up time)."""
    return (rankdata(s, method="average") - 1) / max(len(s) - 1, 1)


class VotePlain(Ranker):
    key = "vote_plain"

    def __init__(self, seed: int):
        self.seed = seed
        self.members = [Connection(seed), MoneyFlow(seed), Similarity(seed), Sync(seed),
                        Rules(seed)]

    def score(self, world: World, known: dict[int, int]) -> np.ndarray:
        pct = np.array([rank_pct(m.score(world, known)) for m in self.members])
        top = (pct >= 1 - TOP_SHARE).sum(axis=0)
        return top + pct.mean(axis=0)                     # ties: the average rank


class Vote(VotePlain):
    key = "vote"

    def __init__(self, seed: int):
        from bench.discover.methods.anchored import ReasonHop, ReasonRules, ReasonSim

        self.seed = seed
        self.members = [ReasonSim(seed), ReasonHop(seed), ReasonRules(seed), Sync(seed),
                        Connection(seed)]
