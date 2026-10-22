"""Score one trace against the hidden truth, and average traces across seed draws.

- **Analyst cost:** bad users found per round of reviews, and recall at the full budget.
- **Ranking:** ROC and PR over the users nobody reviewed.
- **Label set:** the known bad plus the top-ranked unreviewed users, as many as there are bad
  users in truth, so every method's set has the same size.
- **Segments and risk:** stealth recall, false alarms per cohort, approval rate against the
  bad share among approved users when the ranking is used as a block list.
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)

from bench.discover.protocol import Trace
from bench.discover.world import Truth

BLOCK_SHARES = [0.005, 0.01, 0.015, 0.02, 0.03, 0.05, 0.075, 0.1]
CURVE_POINTS = 120
COHORTS = ["base", "promoter", "promoted_friend"]


def _thin(xs: np.ndarray, ys: np.ndarray) -> list[list[float]]:
    keep = np.unique(np.linspace(0, len(xs) - 1, min(CURVE_POINTS, len(xs))).astype(int))
    return [[round(float(xs[i]), 4), round(float(ys[i]), 4)] for i in keep]


def _pos(user_ids: np.ndarray, ids) -> np.ndarray:
    order = np.argsort(user_ids, kind="stable")
    return order[np.searchsorted(user_ids[order], np.asarray(list(ids), dtype=np.int64))]


def summarize(trace: Trace, user_ids: np.ndarray, truth: Truth,
              block_shares: list[float] = BLOCK_SHARES) -> dict:
    n = len(user_ids)
    known = np.full(n, -1)
    if trace.known:
        known[_pos(user_ids, trace.known)] = list(trace.known.values())
    bad = truth.bad
    to_find = int(bad.sum()) - len(trace.seeds)
    found = np.cumsum(trace.hits).tolist()
    out: dict = {
        "found": [int(x) for x in found],
        "hit_rate": [h / len(r) if r else 0.0 for h, r in zip(trace.hits, trace.reviewed)],
        "recall_at_budget": (found[-1] if found else 0) / max(to_find, 1),
    }
    free = known < 0
    s = trace.scores
    y = bad[free]
    if 0 < y.sum() < len(y):
        out["auc"] = float(roc_auc_score(y, s[free]))
        out["pr_auc"] = float(average_precision_score(y, s[free]))
        fpr, tpr, _ = roc_curve(y, s[free])
        prec, rec, _ = precision_recall_curve(y, s[free])
        out["roc"], out["pr"] = _thin(fpr, tpr), _thin(rec[::-1], prec[::-1])
    else:
        out.update(auc=float("nan"), pr_auc=float("nan"), roc=[], pr=[])

    # one ranking of everyone: known bad, then unreviewed by score, then known good
    key = np.where(known == 1, np.inf, np.where(known == 0, -np.inf, s))
    rank = np.lexsort((np.arange(n), -key))
    size = int(bad.sum())
    chosen = np.zeros(n, bool)
    chosen[rank[:size]] = True
    tp = (chosen & bad).sum()
    out["precision"] = tp / max(chosen.sum(), 1)
    out["recall"] = tp / max(size, 1)
    st, vis = bad & truth.stealth, bad & ~truth.stealth
    out["stealth_recall"] = float((chosen & st).sum() / st.sum()) if st.any() else float("nan")
    out["visible_recall"] = float((chosen & vis).sum() / vis.sum()) if vis.any() else float("nan")
    out["false_alarm"] = {c: float(chosen[truth.cohort == c].mean())
                          for c in COHORTS if (truth.cohort == c).any()}
    risk = []
    for share in block_shares:
        blocked = np.zeros(n, bool)
        blocked[rank[:round(share * n)]] = True
        ok = ~blocked
        risk.append([float(ok.mean()), float(bad[ok].mean()) if ok.any() else 0.0])
    out["risk"] = risk
    return out


def aggregate(summaries: list[dict]) -> dict:
    """Mean and spread per numeric field; lists of equal length are averaged elementwise."""
    out: dict = {}
    for k, v in summaries[0].items():
        vals = [s[k] for s in summaries]
        if isinstance(v, (int, float)):
            a = np.array(vals, dtype=float)
            out[k] = {"mean": float(np.nanmean(a)) if np.isfinite(a).any() else float("nan"),
                      "sd": float(np.nanstd(a)) if np.isfinite(a).any() else float("nan")}
        elif isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v) \
                and len({len(x) for x in vals}) == 1:
            a = np.array(vals, dtype=float)
            out[k] = {"mean": a.mean(axis=0).tolist(), "sd": a.std(axis=0).tolist()}
        elif k == "risk":
            out[k] = {"mean": np.mean(np.array(vals, dtype=float), axis=0).tolist()}
        elif isinstance(v, dict):
            out[k] = {c: {"mean": float(np.mean([s[k][c] for s in summaries]))} for c in v}
        else:
            out[k] = vals[0]          # curves: the first draw stands for the method
    return out
