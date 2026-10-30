"""Pair populations and weighted pair metrics for the v3 evaluation.

The population is every pair of profiles inside one split and one platform class (mobile or web).
It is cut into four disjoint strata, sampled uniformly inside each, and re-weighted by the stratum
size, so precision is estimated at the true prevalence instead of on a retrieval shortlist:

    pos   same tmx_fuzzy_device_id
    spec  different tmx, same spec bucket (model, OS version, screen): the look-alikes
    env   different tmx, different spec, same network (privateIp + city)
    rest  everything else
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

STRATA = ("pos", "spec", "env", "rest")


def pairs_of(n: np.ndarray | int) -> np.ndarray | int:
    return n * (n - 1) // 2


def pair_count(*keys: np.ndarray) -> int:
    """Number of row pairs that agree on every key (rows with any key < 0 form no pairs)."""
    ok = np.all([k >= 0 for k in keys], axis=0)
    if ok.sum() < 2:
        return 0
    _, counts = np.unique(np.stack([k[ok] for k in keys], axis=1), axis=0, return_counts=True)
    return int(pairs_of(counts.astype(np.int64)).sum())


def strata_counts(tmx: np.ndarray, spec: np.ndarray, env: np.ndarray) -> dict[str, int]:
    """Exact size of each stratum by inclusion-exclusion over the three keys."""
    n = len(tmx)
    t, s, st = pair_count(tmx), pair_count(spec), pair_count(spec, tmx)
    e, es, et, est = pair_count(env), pair_count(env, spec), pair_count(env, tmx), pair_count(env, spec, tmx)
    pos, spec_n, env_n = t, s - st, e - es - et + est
    return {"pos": pos, "spec": spec_n, "env": env_n, "rest": int(pairs_of(n)) - pos - spec_n - env_n}


class GroupPairs:
    """Uniform sampler over the pairs of rows that share a key."""

    def __init__(self, key: np.ndarray):
        rows = np.flatnonzero(key >= 0)
        order = np.argsort(key[rows], kind="stable")
        self.rows = rows[order]
        _, starts, sizes = np.unique(key[self.rows], return_index=True, return_counts=True)
        keep = sizes >= 2
        self.starts, self.sizes = starts[keep], sizes[keep]
        w = pairs_of(self.sizes.astype(np.float64))
        self.p = w / w.sum() if w.sum() > 0 else w

    def __bool__(self) -> bool:
        return len(self.sizes) > 0

    def sample(self, n: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
        g = rng.choice(len(self.sizes), n, p=self.p)
        i = rng.integers(0, self.sizes[g])
        j = rng.integers(0, self.sizes[g] - 1)
        j = j + (j >= i)
        return self.rows[self.starts[g] + i], self.rows[self.starts[g] + j]


def _same(key: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (key[a] >= 0) & (key[a] == key[b])


def stratum_of(a, b, tmx, spec, env) -> np.ndarray:
    st = np.full(len(a), 3, dtype=np.int8)
    st[_same(env, a, b)] = 2
    st[_same(spec, a, b)] = 1
    st[tmx[a] == tmx[b]] = 0
    return st


def _draw(target: int, want: int, draw, tmx, spec, env, rng, tries: int = 20):
    """Rejection-sample `want` pairs of stratum `target` from a proposal that covers it uniformly."""
    got_a, got_b, have = [], [], 0
    for _ in range(tries):
        if have >= want:
            break
        a, b = draw(max(2 * (want - have), 1000), rng)
        keep = (a != b) & (stratum_of(a, b, tmx, spec, env) == target)
        got_a.append(a[keep])
        got_b.append(b[keep])
        have += int(keep.sum())
    a, b = np.concatenate(got_a)[:want], np.concatenate(got_b)[:want]
    return a, b


@dataclass
class PairSet:
    a: np.ndarray
    b: np.ndarray
    w: np.ndarray         # population pairs each sampled pair stands for
    stratum: np.ndarray   # index into STRATA
    cls: np.ndarray       # 0 mobile, 1 web

    @property
    def y(self) -> np.ndarray:
        return (self.stratum == 0).astype(np.int64)

    def subset(self, mask: np.ndarray) -> PairSet:
        return PairSet(self.a[mask], self.b[mask], self.w[mask], self.stratum[mask], self.cls[mask])

    @staticmethod
    def concat(parts: list[PairSet]) -> PairSet:
        return PairSet(*(np.concatenate([getattr(p, f) for p in parts])
                         for f in ("a", "b", "w", "stratum", "cls")))


def build_pairs(rows: np.ndarray, tmx: np.ndarray, spec: np.ndarray, env: np.ndarray, cls: int,
                sizes: dict[str, int], seed: int) -> tuple[PairSet, dict[str, int]]:
    """Stratified pair sample over all pairs of `rows`, with weights to the true stratum sizes."""
    rng = np.random.default_rng(seed)
    inside = np.zeros(len(tmx), dtype=bool)
    inside[rows] = True
    counts = strata_counts(tmx[rows], spec[rows], env[rows])

    def uniform(n, r):
        return r.choice(rows, n), r.choice(rows, n)

    proposals = {k: GroupPairs(np.where(inside, v, -1)) for k, v in (("pos", tmx), ("spec", spec), ("env", env))}
    parts = []
    for i, name in enumerate(STRATA):
        if counts[name] <= 0:
            continue
        draw = uniform if name == "rest" else proposals[name].sample
        if name != "rest" and not proposals[name]:
            continue
        a, b = _draw(i, sizes[name], draw, tmx, spec, env, rng)
        if len(a) == 0:
            continue
        w = np.full(len(a), counts[name] / len(a))
        parts.append(PairSet(a, b, w, np.full(len(a), i, dtype=np.int8), np.full(len(a), cls, dtype=np.int8)))
    return PairSet.concat(parts), counts


# ---------------------------------------------------------------- weighted metrics


def weighted_ap(score: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    """Average precision with tied scores taken as one threshold: sum_k (R_k - R_k-1) P_k."""
    if (w * y).sum() == 0:
        return float("nan")
    uniq, inv = np.unique(-score, return_inverse=True)  # ascending -score = descending score
    pos = np.bincount(inv, w * y, len(uniq))
    neg = np.bincount(inv, w * (1 - y), len(uniq))
    tp, fp = np.cumsum(pos), np.cumsum(neg)
    precision = tp / np.maximum(tp + fp, 1e-300)
    return float((precision * pos).sum() / pos.sum())


def weighted_auc(score: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    pos, neg = w * (y == 1), w * (y == 0)
    if pos.sum() == 0 or neg.sum() == 0:
        return float("nan")
    uniq, inv = np.unique(score, return_inverse=True)
    pos_at, neg_at = np.bincount(inv, pos, len(uniq)), np.bincount(inv, neg, len(uniq))
    below = np.cumsum(neg_at) - neg_at
    return float((pos_at * (below + 0.5 * neg_at)).sum() / (pos.sum() * neg.sum()))


def weighted_pr_at(score: np.ndarray, y: np.ndarray, w: np.ndarray, t: float) -> tuple[float, float]:
    pred = score >= t
    tp = (w * y * pred).sum()
    return float(tp / max((w * pred).sum(), 1e-12)), float(tp / max((w * y).sum(), 1e-12))


def best_f1_threshold(score: np.ndarray, y: np.ndarray, w: np.ndarray,
                      grid: np.ndarray | None = None) -> float:
    grid = np.linspace(0.5, 0.999, 500) if grid is None else grid
    best, best_t = -1.0, float(grid[0])
    for t in grid:
        p, r = weighted_pr_at(score, y, w, t)
        f1 = 2 * p * r / (p + r) if p + r > 0 else 0.0
        if f1 > best:
            best, best_t = f1, float(t)
    return best_t


def identity_metrics(score: np.ndarray, ps: PairSet, thresholds: dict[str, float]) -> dict:
    """PR AUC, ROC AUC and cutoff table vs tmx, pooled and per class, plus the per-stratum view."""
    out = {}
    for name, mask in (("pooled", np.ones(len(ps.a), bool)), ("mobile", ps.cls == 0), ("web", ps.cls == 1)):
        if not mask.any():
            continue
        s, y, w, st = score[mask], ps.y[mask], ps.w[mask], ps.stratum[mask]
        block = {
            "prevalence": float((w * y).sum() / w.sum()),
            "pr_auc": weighted_ap(s, y, w), "roc_auc": weighted_auc(s, y, w),
            "at": {}, "stratum_roc_auc": {}, "stratum_median": {},
        }
        for label, t in thresholds.items():
            p, r = weighted_pr_at(s, y, w, t)
            block["at"][label] = {"threshold": float(t), "precision": p, "recall": r}
        for i, sname in enumerate(STRATA):
            m = st == i
            if m.any():
                block["stratum_median"][sname] = float(np.median(s[m]))
            if i > 0 and m.any() and (st == 0).any():
                keep = (st == 0) | m
                block["stratum_roc_auc"][f"pos_vs_{sname}"] = weighted_auc(
                    s[keep], y[keep], np.ones(keep.sum()))
        out[name] = block
    return out
