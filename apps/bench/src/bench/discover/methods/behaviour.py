"""Behaviour look-alikes of the known bad: nearest neighbours, a PU classifier, lockstep timing."""

from __future__ import annotations

import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import NearestNeighbors

from bench.discover.features import standardize, user_matrix
from bench.discover.protocol import Ranker
from bench.discover.world import World

# frozen defaults: set before the first scored run, never tuned on truth
KNN = 20                      # neighbours averaged per side
PU_NEG_RATIO = 20             # unlabeled users sampled as negatives per known bad
SYNC_WINDOW_H = 2.0


def split(world: World, known: dict[int, int]) -> tuple[np.ndarray, np.ndarray]:
    bad = [i for i, v in known.items() if v]
    good = [i for i, v in known.items() if not v]
    f = (lambda ids: world.index(np.array(ids)) if ids else np.array([], dtype=int))
    return f(bad), f(good)


def _mean_knn_dist(z: np.ndarray, ref: np.ndarray) -> np.ndarray:
    nn = NearestNeighbors(n_neighbors=min(KNN, len(ref))).fit(z[ref])
    d, _ = nn.kneighbors(z)
    return d.mean(axis=1)


class Similarity(Ranker):
    key = "similarity"

    def __init__(self, seed: int):
        self.seed = seed

    def score(self, world: World, known: dict[int, int]) -> np.ndarray:
        z = standardize(user_matrix(world)[0])
        bad, good = split(world, known)
        s = -_mean_knn_dist(z, bad)
        if len(good):
            s = s + _mean_knn_dist(z, good)
        return s


class PULearn(Ranker):
    key = "pu_learn"

    def __init__(self, seed: int):
        self.seed = seed
        self._round = 0

    def score(self, world: World, known: dict[int, int]) -> np.ndarray:
        self._round += 1
        z = standardize(user_matrix(world)[0])
        bad, good = split(world, known)
        rng = np.random.default_rng([self.seed, self._round])
        free = np.setdiff1d(np.arange(len(z)), np.concatenate([bad, good]))
        unl = rng.choice(free, size=min(len(free), PU_NEG_RATIO * len(bad)), replace=False)
        x = np.concatenate([z[bad], z[good], z[unl]])
        y = np.concatenate([np.ones(len(bad)), np.zeros(len(good) + len(unl))])
        m = LogisticRegression(max_iter=1000, class_weight="balanced").fit(x, y)
        return m.predict_proba(z)[:, 1]


def milestones(world: World) -> pl.DataFrame:
    """Per user, in hours from the world's start: sign-up, first order (and its SKU), bonus."""
    t0 = world.users["created_at"].min()
    hours = (lambda c: ((pl.col(c) - t0).dt.total_seconds() / 3600))
    first = (world.orders.sort("created_at").group_by("user_id", maintain_order=True)
             .first().select("user_id", hours("created_at").alias("t_order"), "sku_id"))
    bonus = (world.bonuses.group_by("invitee_id").agg(pl.col("event_time").min())
             .select(pl.col("invitee_id").alias("user_id"), hours("event_time").alias("t_bonus")))
    return (world.users.select("user_id", hours("created_at").alias("t_signup"))
            .join(first, on="user_id", how="left").join(bonus, on="user_id", how="left"))


class Sync(Ranker):
    """Lockstep: how many known bad users this user moved with, step by step."""

    key = "sync"

    def __init__(self, seed: int):
        self.seed = seed
        self._m: tuple[int, dict[str, np.ndarray]] | None = None

    def _cols(self, world: World) -> dict[str, np.ndarray]:
        if self._m is None or self._m[0] != id(world):
            m = milestones(world)
            self._m = (id(world), {c: m[c].fill_null(np.nan).to_numpy().astype(float)
                                   for c in ("t_signup", "t_order", "t_bonus", "sku_id")})
        return self._m[1]

    def score(self, world: World, known: dict[int, int]) -> np.ndarray:
        c = self._cols(world)
        bad, _ = split(world, known)
        s = np.zeros(len(world.user_ids))
        for b in bad:
            s += np.abs(c["t_signup"] - c["t_signup"][b]) < SYNC_WINDOW_H
            s += ((np.abs(c["t_order"] - c["t_order"][b]) < SYNC_WINDOW_H)
                  & (c["sku_id"] == c["sku_id"][b]))
            s += np.abs(c["t_bonus"] - c["t_bonus"][b]) < SYNC_WINDOW_H
        return s
