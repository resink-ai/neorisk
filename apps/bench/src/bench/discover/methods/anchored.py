"""Methods anchored on why the known bad users are bad (`bench.discover.explain`).

`reason_sim` ranks users by how much of the seeds' anomaly they carry. `reason_hop` first finds
users with that anomaly, which reaches other rings, then walks out from them and the seeds along
edges that touch an anomalous user. `reason_rules` lets only the rules that fire on the known
bad vote. `anomaly` ignores the seeds: how unusual each user is overall (the baseline that
shows what the seeds add).
"""

from __future__ import annotations

import numpy as np
import scipy.sparse as sp

from bench.discover import explain as ex
from bench.discover.methods.graph import _row_normalize, device_graph, known_bad, ppr
from bench.discover.methods.vote import rank_pct
from bench.discover.methods.weak import LF_NAMES, votes
from bench.discover.protocol import Ranker
from bench.discover.world import World

# frozen defaults: set before the first scored run, never tuned on truth
ANCHOR_SHARE = 0.01           # top share of users by reason score that restart the walk
ANCHOR_WEIGHT = 0.5           # restart mass of an anchor, relative to a confirmed bad user
EDGE_SHARPNESS = 8            # an edge keeps max(rank pct of its two ends) ** this of its weight
TIE = 1e-3                    # reason score breaks ties among users the walk never reaches


class ReasonSim(Ranker):
    key = "reason_sim"

    def __init__(self, seed: int):
        self.seed = seed

    def score(self, world: World, known: dict[int, int]) -> np.ndarray:
        return ex.reason_score(world, known)


def anomalous_edges(world: World, a: np.ndarray) -> sp.csr_matrix:
    """The device-and-invite graph with each edge scaled by its more anomalous end."""
    g = device_graph(world).tocoo()
    m = np.maximum(a[g.row], a[g.col]) ** EDGE_SHARPNESS
    return _row_normalize(sp.coo_matrix((g.data * m, (g.row, g.col)), shape=g.shape).tocsr())


class ReasonHop(Ranker):
    key = "reason_hop"

    def __init__(self, seed: int):
        self.seed = seed

    def score(self, world: World, known: dict[int, int]) -> np.ndarray:
        r = ex.reason_score(world, known)
        a = rank_pct(r)
        start = known_bad(world, known)
        unknown = ~np.isin(world.user_ids, np.fromiter(known, dtype=np.int64, count=len(known)))
        k = max(1, round(ANCHOR_SHARE * len(r)))
        cand = np.flatnonzero(unknown & (r > 0))
        anchors = cand[np.lexsort((world.user_ids[cand], -r[cand]))[:k]]
        start[anchors] = np.maximum(start[anchors], ANCHOR_WEIGHT)
        walk = ppr(anomalous_edges(world, a), start)
        return walk / max(walk.max(), 1e-12) + TIE * a


class ReasonRules(Ranker):
    """Each bad-voting rule weighted by how often it fires on the known bad (less the known
    good); the benign rule subtracts by how often it vouches for the known good."""

    key = "reason_rules"

    def __init__(self, seed: int):
        self.seed = seed

    def score(self, world: World, known: dict[int, int]) -> np.ndarray:
        v = votes(world)
        bad = [i for i, x in known.items() if x]
        good = [i for i, x in known.items() if not x]
        rate = (lambda ids, val: (v[world.index(np.array(ids))] == val).mean(axis=0)
                if ids else np.zeros(v.shape[1]))
        benign = LF_NAMES.index("repeat_buyer")
        w = np.maximum(0.0, rate(bad, 1) - rate(good, 1))
        w[benign] = 0.0
        wb = max(0.0, rate(good, 0)[benign] - rate(bad, 0)[benign])
        return (v == 1).astype(float) @ w - wb * (v[:, benign] == 0)


class Anomaly(Ranker):
    key = "anomaly"

    def __init__(self, seed: int):
        self.seed = seed

    def score(self, world: World, known: dict[int, int]) -> np.ndarray:
        return ex.anomaly_profile(world).sum(axis=1)
