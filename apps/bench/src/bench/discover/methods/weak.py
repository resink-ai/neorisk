"""Frozen labeling functions, written from the published referral rules, and two ways to
combine them: a plain vote and a Dawid-Skene label model.

Each function votes 1 (bad), 0 (benign) or -1 (abstain) for every user.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from bench.discover.features import NAMES, user_devices, user_matrix
from bench.discover.methods.behaviour import split
from bench.discover.protocol import Ranker
from bench.discover.world import World

# frozen defaults: set before the first scored run, never tuned on truth
INVITER_MIN_BONUSES = 3
INVITEE_MAX_MEAN_ORDERS = 2.0
VIEWS_PCTL = 5
EM_ITERS = 20
LF_NAMES = ["min_order_on_cheapest", "one_order_then_silent", "inviter_device",
            "bonus_farm_inviter", "few_views", "repeat_buyer"]
_CACHE: dict[int, np.ndarray] = {}


def votes(world: World) -> np.ndarray:
    key = id(world)
    if key in _CACHE:
        return _CACHE[key]
    x, _ = user_matrix(world)
    col = {n: x[:, i] for i, n in enumerate(NAMES)}
    n = len(world.user_ids)
    v = np.full((n, len(LF_NAMES)), -1, dtype=int)
    has = col["orders"] > 0
    # 1. every order is sized to the minimum on the cheapest qualifying SKU
    v[has & (col["near_min_share"] == 1) & (col["cheapest_share"] == 1), 0] = 1
    # 2. invited, one order, then no session after the bonus
    last = world.sessions.group_by("user_id").agg(pl.col("event_time").max().alias("last"))
    bonus = world.bonuses.group_by("invitee_id").agg(pl.col("event_time").min().alias("paid"))
    t = (world.users.select("user_id").join(last, on="user_id", how="left")
         .join(bonus, left_on="user_id", right_on="invitee_id", how="left"))
    silent = (t["paid"].is_not_null() & (t["last"].is_null() | (t["last"] <= t["paid"])))
    v[(col["invited"] == 1) & (col["orders"] == 1) & silent.to_numpy(), 1] = 1
    # 3. signed up on a device the inviter also uses
    ud = user_devices(world)
    su = world.signups.drop_nulls("invited_by").select("user_id", "device_id", "invited_by")
    shared = su.join(ud, left_on=["invited_by", "device_id"], right_on=["user_id", "device_id"],
                     how="semi")["user_id"].unique()
    if shared.len():
        v[world.index(shared.to_numpy()), 2] = 1
    # 4. an inviter with many paid bonuses whose invitees barely buy
    orders = pl.DataFrame({"user_id": world.user_ids, "o": col["orders"]})
    farm = (world.users.drop_nulls("invited_by").join(orders, on="user_id")
            .group_by("invited_by").agg(pl.col("o").mean().alias("mean_o"))
            .join(world.bonuses.group_by("user_id").agg(pl.len().alias("b")),
                  left_on="invited_by", right_on="user_id")
            .filter((pl.col("b") >= INVITER_MIN_BONUSES)
                    & (pl.col("mean_o") < INVITEE_MAX_MEAN_ORDERS)))["invited_by"]
    if farm.len():
        v[world.index(farm.to_numpy()), 3] = 1
    # 5. hardly browses: views per order below the population's 5th percentile
    vpo = col["views_per_order"]
    if has.any():
        v[has & (vpo < np.percentile(vpo[has], VIEWS_PCTL)), 4] = 1
    # 6. benign: two or more orders off the qualifying minimum
    off_min = col["orders"] * (1 - col["near_min_share"])
    v[off_min >= 2, 5] = 0
    _CACHE[key] = v
    return v


class Rules(Ranker):
    """Majority vote: bad votes minus benign votes."""

    key = "rules"

    def __init__(self, seed: int):
        self.seed = seed

    def score(self, world: World, known: dict[int, int]) -> np.ndarray:
        v = votes(world)
        return (v == 1).sum(axis=1) - (v == 0).sum(axis=1).astype(float)


def dawid_skene(v: np.ndarray, clamp: dict[int, float]) -> np.ndarray:
    """One-coin Dawid-Skene: each function has an accuracy; returns P(bad) per user."""
    n, m = v.shape
    acc = np.full(m, 0.7)
    prior = 0.05
    idx = np.fromiter(clamp, dtype=int, count=len(clamp))
    val = np.fromiter(clamp.values(), dtype=float, count=len(clamp))
    for _ in range(EM_ITERS):
        lp1 = np.full(n, np.log(prior))
        lp0 = np.full(n, np.log(1 - prior))
        for j in range(m):
            a = np.clip(acc[j], 0.5, 0.95)     # better than chance: keeps EM from flipping
            lp1 += np.where(v[:, j] == 1, np.log(a), np.where(v[:, j] == 0, np.log(1 - a), 0))
            lp0 += np.where(v[:, j] == 0, np.log(a), np.where(v[:, j] == 1, np.log(1 - a), 0))
        p = 1 / (1 + np.exp(np.clip(lp0 - lp1, -50, 50)))
        p[idx] = val
        for j in range(m):
            on = v[:, j] >= 0
            if on.any():
                acc[j] = (np.where(v[on, j] == 1, p[on], 1 - p[on])).mean()
        prior = float(np.clip(p.mean(), 1e-4, 0.5))
    return p


class LabelModel(Ranker):
    key = "label_model"

    def __init__(self, seed: int):
        self.seed = seed

    def score(self, world: World, known: dict[int, int]) -> np.ndarray:
        bad, good = split(world, known)
        clamp = {**{int(i): 1.0 for i in bad}, **{int(i): 0.0 for i in good}}
        return dawid_skene(votes(world), clamp)
