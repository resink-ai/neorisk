"""Graph expansion from known bad users: shared devices and invites, or the bonus money."""

from __future__ import annotations

import numpy as np
import polars as pl
import scipy.sparse as sp

from bench.discover.features import user_devices
from bench.discover.protocol import Ranker
from bench.discover.world import World

# frozen defaults: set before the first scored run, never tuned on truth
ALPHA = 0.15                  # restart probability
ITERS = 30


def _pairs(world: World, df: pl.DataFrame, a: str, b: str, w: np.ndarray, n: int):
    i = world.index(df[a].to_numpy())
    j = world.index(df[b].to_numpy())
    m = sp.coo_matrix((w, (i, j)), shape=(n, n)).tocsr()
    return m + m.T


def _row_normalize(a: sp.csr_matrix) -> sp.csr_matrix:
    a = a.tocsr()
    a.setdiag(0)
    a.eliminate_zeros()
    deg = np.asarray(a.sum(axis=1)).ravel()
    return sp.diags(np.where(deg > 0, 1 / np.where(deg > 0, deg, 1), 0)) @ a


def invite_edges(world: World) -> pl.DataFrame:
    return world.users.drop_nulls("invited_by").select("user_id", "invited_by")


def device_graph(world: World) -> sp.csr_matrix:
    """Users linked through each shared device (weight 1/log(1+users on it)) and by invites."""
    key = "graph:device"
    if key not in world.cache:
        n = len(world.user_ids)
        ud = user_devices(world)
        dev = ud["device_id"].unique().sort()
        di = np.searchsorted(dev.to_numpy(), ud["device_id"].to_numpy())
        ui = world.index(ud["user_id"].to_numpy())
        inc = sp.coo_matrix((np.ones(len(ui)), (ui, di)), shape=(n, len(dev))).tocsr()
        users_on = np.asarray(inc.sum(axis=0)).ravel()
        w = sp.diags(1 / np.log1p(users_on))
        a = inc @ w @ inc.T
        inv = invite_edges(world)
        a = a + _pairs(world, inv, "user_id", "invited_by", np.ones(inv.height), n)
        world.cache[key] = _row_normalize(a)
    return world.cache[key]


def money_graph(world: World) -> sp.csr_matrix:
    """Inviter-invitee links weighted by 1 + the bonuses paid on them."""
    key = "graph:money"
    if key not in world.cache:
        n = len(world.user_ids)
        inv = invite_edges(world)
        paid = world.bonuses.group_by("user_id", "invitee_id").agg(pl.len().alias("b"))
        e = inv.join(paid, left_on=["invited_by", "user_id"], right_on=["user_id", "invitee_id"],
                     how="left").with_columns(pl.col("b").fill_null(0))
        world.cache[key] = _row_normalize(
            _pairs(world, e, "user_id", "invited_by", 1.0 + e["b"].to_numpy(), n))
    return world.cache[key]


def ppr(p: sp.csr_matrix, start: np.ndarray) -> np.ndarray:
    """Personalized PageRank: random walks that restart on `start` (a 0/1 vector)."""
    if start.sum() == 0:
        return np.zeros(len(start))
    s = start / start.sum()
    r = s.copy()
    pt = p.T.tocsr()
    for _ in range(ITERS):
        r = ALPHA * s + (1 - ALPHA) * (pt @ r)
    return r


def known_bad(world: World, known: dict[int, int]) -> np.ndarray:
    bad = [i for i, v in known.items() if v]
    start = np.zeros(len(world.user_ids))
    if bad:
        start[world.index(np.array(bad))] = 1.0
    return start


class Connection(Ranker):
    key = "connection"

    def __init__(self, seed: int):
        self.seed = seed

    def score(self, world: World, known: dict[int, int]) -> np.ndarray:
        return ppr(device_graph(world), known_bad(world, known))


class MoneyFlow(Ranker):
    key = "money_flow"

    def __init__(self, seed: int):
        self.seed = seed

    def score(self, world: World, known: dict[int, int]) -> np.ndarray:
        return ppr(money_graph(world), known_bad(world, known))
