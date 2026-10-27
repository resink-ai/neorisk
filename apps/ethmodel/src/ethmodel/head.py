"""The head and the scores built on it.

pu_scores    positive-unlabeled logistic regression: trust-weighted positives against
             everyone else (unlabeled, never assumed good); reviewed "not bad" count as real
             negatives with double weight
graph_scores one hop: the value-weighted share of an address's flow to or from known bad ones
blend        rank of the head score, plus the graph share
recall_at    held-out positives found in the top k
"""

from __future__ import annotations

import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ETH_USD = 3000.0   # a fixed rate: value weights only need the order of magnitude


def pu_scores(x: np.ndarray, positive: np.ndarray, weight: np.ndarray,
              negative: np.ndarray | None = None, *, seed: int = 7) -> np.ndarray:
    """x [n, d]; positive bool [n]; weight [n] (trust for positives); negative bool [n]."""
    if positive.sum() == 0:
        return np.zeros(len(x))
    z = StandardScaler().fit_transform(x)
    w = np.where(positive, weight, 1.0)
    if negative is not None:
        w = np.where(negative & ~positive, 2.0, w)
    clf = LogisticRegression(C=1.0, max_iter=2000, random_state=seed)
    clf.fit(z, positive.astype(int), sample_weight=w)
    return clf.predict_proba(z)[:, 1]


def graph_scores(transfers: pl.DataFrame, bad: set[str]) -> dict[str, float]:
    """address -> share of its USD-ish flow whose other side is in `bad`. Unpriced tokens
    count one unit each, so they still register as contact."""
    value = (pl.when(pl.col("usd_approx").is_not_null()).then(pl.col("usd_approx"))
             .when(pl.col("asset") == "ETH").then(pl.col("amount") * ETH_USD)
             .otherwise(1.0))
    tr = transfers.with_columns(value.fill_null(0.0).alias("v"))
    sides = pl.concat([
        tr.select(pl.col("from_address").alias("a"), pl.col("to_address").alias("b"), "v"),
        tr.select(pl.col("to_address").alias("a"), pl.col("from_address").alias("b"), "v")])
    sides = sides.filter(pl.col("a").is_not_null() & (pl.col("a") != pl.col("b")))
    agg = sides.group_by("a").agg(pl.col("v").sum().alias("total"),
                                  pl.col("v").filter(pl.col("b").is_in(list(bad))).sum()
                                  .alias("bad"))
    return {a: (b / t if t > 0 else 0.0) for a, t, b in agg.select("a", "total", "bad").rows()}


def rank01(s: np.ndarray) -> np.ndarray:
    """Percentile rank in [0, 1], ties averaged."""
    if len(s) < 2:
        return np.zeros(len(s))
    order = s.argsort(kind="stable")
    r = np.empty(len(s))
    r[order] = np.arange(len(s))
    for v in np.unique(s):   # average ties so equal scores rank equally
        m = s == v
        r[m] = r[m].mean()
    return r / (len(s) - 1)


def blend(head: np.ndarray, graph: np.ndarray, graph_weight: float = 0.3) -> np.ndarray:
    return (1 - graph_weight) * rank01(head) + graph_weight * graph


def recall_at(scores: np.ndarray, names: list[str], held: set[str], k: int = 100) -> float:
    top = {names[i] for i in np.argsort(-scores, kind="stable")[:k]}
    return len(top & held) / len(held) if held else float("nan")
