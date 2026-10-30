"""Does the embedding space behave as asked: the same device close, similar devices closer than
dissimilar ones, different devices far apart?

On the test devices of one fold:
  distances      quantiles of euclidean distance for same-device and different-device pairs
  similarity     for different-device pairs, mean distance by how many profile fields differ
                 (Spearman correlation over all pairs): similar devices should sit closer
  margin         share of fingerprints whose nearest other-device neighbour is farther than
                 their farthest same-device fingerprint
"""

from __future__ import annotations

import numpy as np
import polars as pl

from devicefp import evaluate as ev
from devicefp.profiles import Profiles


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra = pl.Series(a).rank().to_numpy()
    rb = pl.Series(b).rank().to_numpy()
    return float(np.corrcoef(ra, rb)[0, 1])


def geometry(p: Profiles, z: np.ndarray, rows: np.ndarray, max_rows: int = 2500,
             seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    rows = np.sort(rows if len(rows) <= max_rows else rng.choice(rows, max_rows, replace=False))
    devices = p.table["device"].to_numpy()[rows]
    d = ev.euclidean(z)(rows, rows)
    mism = ev.hamming(ev.codes(p))(rows, rows)
    iu = np.triu_indices(len(rows), 1)
    same = devices[iu[0]] == devices[iu[1]]
    dd, mm = d[iu], mism[iu]
    q = [0.05, 0.25, 0.5, 0.75, 0.95]
    out = {
        "same_device": dict(zip(map(str, q), np.quantile(dd[same], q).round(3).tolist(),
                                strict=True)),
        "different_device": dict(zip(map(str, q), np.quantile(dd[~same], q).round(3).tolist(),
                                     strict=True)),
        "spearman_distance_vs_fields_differing": _spearman(dd[~same], mm[~same]),
    }
    diff = pl.DataFrame({"fields_differing": mm[~same].astype(int), "distance": dd[~same]})
    out["by_fields_differing"] = (
        diff.with_columns(pl.col("fields_differing").clip(upper_bound=20))
        .group_by("fields_differing").agg(pl.len().alias("pairs"),
                                          pl.col("distance").mean().round(3).alias("mean"))
        .sort("fields_differing").to_dicts())
    eye = np.eye(len(rows), dtype=bool)
    same_m = (devices[:, None] == devices[None, :]) & ~eye
    has = same_m.any(1)
    far_same = np.where(same_m, d, -np.inf).max(1)
    near_other = np.where(~same_m & ~eye, d, np.inf).min(1)
    out["margin_ok"] = float((near_other[has] > far_same[has]).mean())
    return out
