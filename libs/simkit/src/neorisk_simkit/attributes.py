from dataclasses import dataclass
from enum import Enum

import numpy as np
import polars as pl

DAY = np.timedelta64(1, "D")
_US_PER_DAY = 86_400_000_000


class Cardinality(str, Enum):
    LOW = "low"
    HIGH = "high"


class Volatility(str, Enum):
    STATIC = "static"
    SLOW = "slow"
    FAST = "fast"


# expected change points per entity per day
RATES = {Volatility.STATIC: 0.0, Volatility.SLOW: 1 / 90, Volatility.FAST: 1 / 2}
DEFAULT_K = {Cardinality.LOW: 10, Cardinality.HIGH: 1_000_000}


@dataclass(frozen=True)
class AttrSpec:
    name: str
    cardinality: Cardinality = Cardinality.LOW
    volatility: Volatility = Volatility.STATIC
    k: int | None = None

    @property
    def size(self) -> int:
        k = DEFAULT_K[self.cardinality] if self.k is None else self.k
        if k < 2:
            raise ValueError(f"attribute {self.name!r}: k must be >= 2, got {k}")
        return k


def _reflect(x: np.ndarray, k: int) -> np.ndarray:
    """Fold an unbounded walk into [0, k-1] with reflecting boundaries."""
    period = 2 * (k - 1)
    m = np.mod(x, period)
    return np.where(m <= k - 1, m, period - m)


def sample_timeline(
    spec: AttrSpec, created_at: np.ndarray, t1: np.datetime64, rng: np.random.Generator
) -> pl.DataFrame:
    """Long-form (idx, valid_from, value) timeline for one attribute.

    Each entity starts with an independent draw at ``created_at``; change points are
    Poisson in time. SLOW/STATIC redraw; FAST attributes take +-s random-walk steps that
    reflect at 0 and k-1 (a triangle-wave fold of ``init + cumsum``), so they never stick
    at a bound.
    """
    if len(created_at) and (created_at > t1).any():
        raise ValueError("created_at must not be after t1")
    n = len(created_at)
    k = spec.size
    init = rng.integers(0, k, size=n)
    idx_parts = [np.arange(n, dtype="int64")]
    time_parts = [created_at]
    value_parts = [init]

    dur_days = (t1 - created_at) / DAY
    counts = rng.poisson(RATES[spec.volatility] * dur_days)
    total = int(counts.sum())
    if total:
        idx = np.repeat(np.arange(n, dtype="int64"), counts)
        offs = (rng.random(total) * dur_days[idx] * _US_PER_DAY).astype("int64")
        times = created_at[idx] + offs.astype("timedelta64[us]")
        order = np.lexsort((times, idx))
        idx, times = idx[order], times[order]
        if spec.volatility is Volatility.FAST:
            s = 1 if spec.cardinality is Cardinality.LOW else max(1, k // 100)
            steps = rng.choice(np.array([-s, s]), size=total)
            cum = (
                pl.DataFrame({"idx": idx, "step": steps})
                .with_columns(c=pl.col("step").cum_sum().over("idx"))["c"]
                .to_numpy()
            )
            values = _reflect(init[idx] + cum, k)
        else:
            values = rng.integers(0, k, size=total)
        idx_parts.append(idx)
        time_parts.append(times)
        value_parts.append(values)

    return pl.DataFrame(
        {
            "idx": np.concatenate(idx_parts),
            "valid_from": np.concatenate(time_parts),
            "value": np.concatenate(value_parts).astype("int64"),
        }
    ).sort("idx", "valid_from")
