"""Splits, baselines and the linking / verification protocols.

Devices, not fingerprints, are split: a test device is never seen in training. Inside the test
set the protocols are:

  track    FP-Stalker's setting. Fingerprints arrive in time order; each one is compared with
           the latest fingerprint of every device seen so far. A returning device should rank
           its own latest fingerprint first; a new device should be farther than a threshold
           from everything (threshold tuned on the validation devices).
  enroll   each device is enrolled once with its first fingerprint; every later fingerprint is
           matched against all enrolments. Accuracy is broken down by time since enrolment.
  verify   all pairs of test fingerprints: same device or not, from the distance alone
           (ROC-AUC, EER, true-accept rate at a fixed false-accept rate).

Every scorer is a function dist(query_rows, gallery_rows) -> [q, g] distance matrix over row
indices of one profile table, so embeddings and baselines go through the same code.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import polars as pl

from devicefp.profiles import Profiles

Dist = Callable[[np.ndarray, np.ndarray], np.ndarray]


def split_devices(p: Profiles, fold: int = 0, folds: int = 5, val: float = 0.1,
                  seed: int = 7, group: str = "consistent") -> dict[str, str]:
    """device -> train / val / test. Devices are shuffled once (by `seed`) and cut into
    `folds` parts; part `fold` is the test set, `val` of the rest is the validation set.
    Stratified by whether the device has more than one fingerprint."""
    counts = p.table.filter(pl.col("group") == group).group_by("device").len().sort("device")
    rng = np.random.default_rng(seed)
    out: dict[str, str] = {}
    for multi in (True, False):
        ids = counts.filter((pl.col("len") > 1) == multi)["device"].to_numpy()
        ids = ids[rng.permutation(len(ids))]
        part = np.arange(len(ids)) * folds // len(ids)
        rest = ids[part != fold]
        n_val = round(len(rest) * val)
        for d in ids[part == fold]:
            out[str(d)] = "test"
        for i, d in enumerate(rest):
            out[str(d)] = "val" if i < n_val else "train"
    return out


# scorers --------------------------------------------------------------------------------------

def euclidean(z: np.ndarray) -> Dist:
    def dist(q, g):
        a, b = z[q], z[g]
        d2 = (a * a).sum(1)[:, None] + (b * b).sum(1)[None, :] - 2 * a @ b.T
        return np.sqrt(np.clip(d2, 0, None))
    return dist


def codes(p: Profiles) -> np.ndarray:
    """[rows, fields] integer code of each field value (a set as its sorted, joined items)."""
    cols = []
    for f in p.fields:
        c = p.table[f.name]
        if f.kind == "set":
            c = c.list.sort().list.join("\x1f")
        cols.append(c.fill_null("").cast(pl.Categorical).to_physical().to_numpy())
    return np.stack(cols, 1).astype(np.int64)


def hamming(c: np.ndarray) -> Dist:
    """How many fields differ."""
    def dist(q, g):
        return (c[q][:, None, :] != c[g][None, :, :]).sum(2).astype(np.float32)
    return dist


@dataclass
class NaiveBayes:
    """Per-field log-likelihood ratio, fitted on training devices: a field that matches is
    worth log(P(match|same)/P(match|different)), a field that differs log(P(diff|same)/
    P(diff|different)). Distance is minus the summed ratio. Eckersley's Panopticlick linker
    and FP-Stalker's rules are hand-tuned versions of this idea."""
    match: np.ndarray       # [fields] weight when equal
    differ: np.ndarray      # [fields] weight when different
    p_change: np.ndarray    # [fields] P(differ | same device), consecutive fingerprints

    @classmethod
    def fit(cls, c: np.ndarray, devices: np.ndarray, rows: np.ndarray) -> NaiveBayes:
        # P(differ | same device): consecutive fingerprints of one device (rows are in time
        # order in the profile table)
        by_dev: dict[str, list[int]] = {}
        for r in np.sort(rows):
            by_dev.setdefault(devices[r], []).append(r)
        pairs = [(a, b) for rs in by_dev.values() for a, b in itertools.pairwise(rs)]
        if pairs:
            a, b = np.array(pairs).T
            p_change = (c[a] != c[b]).mean(0)
        else:
            p_change = np.full(c.shape[1], 0.1)
        # P(match | different devices): one fingerprint per device, value collision rate
        firsts = np.array([rs[0] for rs in by_dev.values()])
        p_collide = np.array([np.square(np.unique(c[firsts, f], return_counts=True)[1]
                                        / len(firsts)).sum() for f in range(c.shape[1])])
        eps = 1e-3
        p_change = np.clip(p_change, eps, 1 - eps)
        p_collide = np.clip(p_collide, eps, 1 - eps)
        return cls(np.log((1 - p_change) / p_collide), np.log(p_change / (1 - p_collide)),
                   p_change)

    def scorer(self, c: np.ndarray) -> Dist:
        def dist(q, g):
            eq = c[q][:, None, :] == c[g][None, :, :]
            return -np.where(eq, self.match, self.differ).sum(2).astype(np.float32)
        return dist


# protocols ------------------------------------------------------------------------------------

def track(dist: Dist, devices: np.ndarray, rows: np.ndarray) -> pl.DataFrame:
    """One record per fingerprint in time order: is the device already known, the rank of its
    own latest fingerprint (returning devices), and the nearest distance to any gallery item."""
    latest: dict[str, int] = {}
    out = []
    for r in np.sort(rows):
        dev = devices[r]
        gal_dev = list(latest)
        if gal_dev:
            g = np.array([latest[d] for d in gal_dev])
            d = dist(np.array([r]), g)[0]
            nearest = float(d.min())
            if dev in latest:
                own = d[gal_dev.index(dev)]
                rank = int((d < own).sum()) + 1
            else:
                rank = None
        else:
            nearest, rank = float("inf"), None
        out.append({"row": int(r), "returning": dev in latest, "rank": rank,
                    "nearest": nearest, "gallery": len(gal_dev)})
        latest[dev] = int(r)
    return pl.DataFrame(out, schema={"row": pl.Int64, "returning": pl.Boolean,
                                     "rank": pl.Int64, "nearest": pl.Float64,
                                     "gallery": pl.Int64})


def open_set(t: pl.DataFrame, threshold: float) -> dict[str, float]:
    """Decide per fingerprint: link to the nearest device if nearer than the threshold, else
    call it new. Correct = linked to the right device, or a new device called new."""
    known = t.filter(pl.col("gallery") > 0)
    ret, new = known.filter(pl.col("returning")), known.filter(~pl.col("returning"))
    link_ok = ((ret["rank"] == 1) & (ret["nearest"] <= threshold)).sum()
    new_ok = (new["nearest"] > threshold).sum()
    return {"open_set_acc": float((link_ok + new_ok) / max(known.height, 1)),
            "returning_linked": float(link_ok / max(ret.height, 1)),
            "new_rejected": float(new_ok / max(new.height, 1))}


def best_threshold(t: pl.DataFrame) -> float:
    cands = np.unique(t.filter(pl.col("nearest").is_finite())["nearest"].to_numpy())
    if len(cands) > 400:
        cands = np.quantile(cands, np.linspace(0, 1, 400))
    scores = [open_set(t, x)["open_set_acc"] for x in cands]
    return float(cands[int(np.argmax(scores))])


def track_metrics(t: pl.DataFrame, threshold: float) -> dict[str, float]:
    ret = t.filter(pl.col("returning"))
    rank = ret["rank"].to_numpy()
    return {"queries": ret.height, "top1": float((rank == 1).mean()),
            "top5": float((rank <= 5).mean()), "mrr": float((1 / rank).mean()),
            **open_set(t, threshold), "threshold": threshold}


def enroll(dist: Dist, devices: np.ndarray, seen_days: np.ndarray,
           rows: np.ndarray) -> pl.DataFrame:
    rows = np.sort(rows)
    first: dict[str, int] = {}
    for r in rows:
        first.setdefault(devices[r], int(r))
    gal_dev = list(first)
    g = np.array([first[d] for d in gal_dev])
    pos = {d: i for i, d in enumerate(gal_dev)}
    q = np.array([r for r in rows if first[devices[r]] != r])
    if len(q) == 0:
        return pl.DataFrame(schema={"row": pl.Int64, "rank": pl.Int64, "days": pl.Float64})
    out = []
    for s in range(0, len(q), 256):
        qs = q[s:s + 256]
        d = dist(qs, g)
        own = d[np.arange(len(qs)), [pos[devices[r]] for r in qs]]
        ranks = (d < own[:, None]).sum(1) + 1
        for r, k in zip(qs, ranks, strict=True):
            out.append({"row": int(r), "rank": int(k),
                        "days": float(seen_days[r] - seen_days[first[devices[r]]])})
    return pl.DataFrame(out)


GAPS = [(0, 7, "<1 week"), (7, 30, "1-4 weeks"), (30, 90, "1-3 months"),
        (90, 10_000, ">3 months")]


def enroll_metrics(e: pl.DataFrame) -> dict[str, float]:
    out = {"queries": e.height, "top1": float((e["rank"] == 1).mean())}
    for lo, hi, name in GAPS:
        s = e.filter((pl.col("days") >= lo) & (pl.col("days") < hi))
        out[f"top1 {name}"] = float((s["rank"] == 1).mean()) if s.height else float("nan")
        out[f"n {name}"] = s.height
    return out


def verify(dist: Dist, devices: np.ndarray, rows: np.ndarray) -> dict[str, float]:
    """All pairs among rows: ROC-AUC, EER and TAR at FAR 1% / 0.1%."""
    rows = np.sort(rows)
    d = dist(rows, rows)
    iu = np.triu_indices(len(rows), 1)
    dd = d[iu]
    same = devices[rows][iu[0]] == devices[rows][iu[1]]
    pos, neg = dd[same], dd[~same]
    out = {"pairs_same": len(pos), "pairs_diff": len(neg)}
    # AUC = P(d_pos < d_neg) + 0.5 P(tie), by ranks
    allv = np.concatenate([pos, neg])
    ranks = _avg_ranks(allv)
    out["roc_auc"] = float((ranks[len(pos):].sum() - len(neg) * (len(neg) + 1) / 2)
                           / (len(pos) * len(neg)))
    negs = np.sort(neg)
    for far in (0.01, 0.001):
        thr = negs[int(far * len(negs))]
        out[f"tar@far={far:g}"] = float((pos < thr).mean())
    ts = np.quantile(allv, np.linspace(0, 1, 2001))
    frr = np.array([(pos > t).mean() for t in ts])
    far_ = np.array([(neg <= t).mean() for t in ts])
    k = int(np.argmin(np.abs(frr - far_)))
    out["eer"] = float((frr[k] + far_[k]) / 2)
    return out


def _avg_ranks(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x))
    ranks[order] = np.arange(1, len(x) + 1)
    xs = x[order]
    # average ranks over ties
    _, start, cnt = np.unique(xs, return_index=True, return_counts=True)
    for s, c in zip(start, cnt, strict=True):
        if c > 1:
            ranks[order[s:s + c]] = s + (c + 1) / 2
    return ranks
