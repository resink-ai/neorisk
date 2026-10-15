from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import polars as pl

Chooser = Callable[[np.ndarray, np.random.Generator], np.ndarray]


def uniform(m: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    return np.floor(rng.random(len(m)) * m).astype("int64")


def skewed(alpha: float) -> Chooser:
    def choose(m: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        return np.floor(m * rng.random(len(m)) ** alpha).astype("int64")

    return choose


def hubs(hub_idx: np.ndarray, p: float, base: Chooser = uniform) -> Chooser:
    """With probability ``p`` pick uniformly among hubs that already exist, else ``base``."""
    hub_idx = np.sort(np.asarray(hub_idx, dtype="int64"))

    def choose(m: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        out = base(m, rng)
        n_elig = np.searchsorted(hub_idx, m, side="left")  # hubs with idx < m
        use = (rng.random(len(m)) < p) & (n_elig > 0)
        pick = np.floor(rng.random(len(m)) * np.maximum(n_elig, 1)).astype("int64")
        out[use] = hub_idx[pick[use]]
        return out

    return choose


@dataclass(frozen=True)
class RefSpec:
    column: str
    target: str  # target entity name
    chooser: Chooser
    null_prob: float = 0.0
    strict: bool = True  # referenced entity must be created strictly before the row


def resolve_reference(
    spec: RefSpec, times: np.ndarray, target_created_at: np.ndarray, rng: np.random.Generator
) -> pl.Series:
    """Fill a reference column with idx of target entities that exist at ``times``.

    ``target_created_at`` must be sorted ascending (entity ``idx`` is the rank by creation
    time), so the entities that exist at ``t`` are exactly ``idx < m`` with
    ``m = searchsorted(target_created_at, t)``. A ``ValueError`` is raised otherwise.
    With ``spec.strict`` the target must be created strictly before ``t``; otherwise an
    entity created at the same instant is eligible too. Rows with no eligible target (or
    dropped by ``null_prob``) are null.
    """
    if len(target_created_at) > 1 and (target_created_at[1:] < target_created_at[:-1]).any():
        raise ValueError("target_created_at must be sorted ascending")
    side = "left" if spec.strict else "right"
    m = np.searchsorted(target_created_at, times, side=side)
    idx = spec.chooser(m, rng)
    ok = (m > 0) & (rng.random(len(m)) >= spec.null_prob)
    return (
        pl.DataFrame({"v": idx.astype("int64"), "ok": ok})
        .select(pl.when(pl.col("ok")).then(pl.col("v")).alias(spec.column))
        .to_series()
    )
