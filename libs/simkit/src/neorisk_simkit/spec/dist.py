"""Distribution descriptors. Durations are encoded in microseconds."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

(CONST, EXP, LOGNORMAL, SHIFTED_LOGNORMAL, GAMMA, NORMAL, PARETO, GEOMETRIC, NEGBINOM,
 UNIFORM_INT, CATEGORICAL, ZIPF, POISSON_DAILY, LOGNORMAL_MINOR) = range(14)

_MS = 1_000.0
_S = 1_000_000.0
_H = 3_600.0 * _S
_DAY = 24 * _H


@dataclass(frozen=True)
class Dist:
    kind: int
    params: tuple[float, float, float]
    labels: tuple = ()
    weights: tuple[float, ...] = ()


def _finite(name: str, v: float) -> float:
    """NaN or an infinite parameter would sample garbage silently; refuse it up front."""
    if not math.isfinite(v):
        raise ValueError(f"{name} must be finite, got {v}")
    return float(v)


_INT_LIMIT = 2**62                     # sampled integers are clipped to [0, 2**62] (sample_np)


def _int_bound(name: str, v: float, lo: float = 0) -> float:
    """An integer-valued bound: finite, whole and in `[lo, 2**62]`."""
    _finite(name, v)
    if float(v) != math.floor(v):
        raise ValueError(f"{name} must be an integer, got {v}")
    if not lo <= v <= _INT_LIMIT:
        raise ValueError(f"{name} must be in [{lo}, 2**62], got {v}")
    return float(v)


def _pos(name: str, v: float) -> float:
    if not v > 0:
        raise ValueError(f"{name} must be > 0, got {v}")
    return _finite(name, v)


def _one(what: str, **kw: float | None) -> tuple[str, float]:
    given = [(k, v) for k, v in kw.items() if v is not None]
    if len(given) != 1:
        raise ValueError(f"{what}: give exactly one of {', '.join(kw)}")
    return given[0]


def constant(ms: float | None = None, s: float | None = None) -> Dist:
    k, v = _one("constant", ms=ms, s=s)
    _finite(k, v)
    if v < 0:
        raise ValueError("constant must be >= 0")
    return Dist(CONST, (v * (_MS if k == "ms" else _S), 0.0, 0.0))


def exp(mean_s: float | None = None, mean_days: float | None = None) -> Dist:
    k, v = _one("exp", mean_s=mean_s, mean_days=mean_days)
    _pos(k, v)
    return Dist(EXP, (v * (_S if k == "mean_s" else _DAY), 0.0, 0.0))


def lognormal(median_s: float | None = None, median_ms: float | None = None,
              sigma: float = 0.6) -> Dist:
    k, v = _one("lognormal", median_s=median_s, median_ms=median_ms)
    _pos(k, v)
    _pos("sigma", sigma)
    return Dist(LOGNORMAL, (v * (_S if k == "median_s" else _MS), float(sigma), 0.0))


def shifted_lognormal(min_ms: float, median_ms: float, sigma: float = 0.5) -> Dist:
    _finite("min_ms", min_ms)
    _finite("median_ms", median_ms)
    if min_ms < 0:
        raise ValueError("min_ms must be >= 0")
    if not median_ms > min_ms:
        raise ValueError("median_ms must be greater than min_ms")
    _pos("sigma", sigma)
    return Dist(SHIFTED_LOGNORMAL,
                (min_ms * _MS, (median_ms - min_ms) * _MS, float(sigma)))


def gamma(mean_days: float | None = None, mean_s: float | None = None, shape: float = 2.0,
          max_days: float | None = None) -> Dist:
    k, v = _one("gamma", mean_days=mean_days, mean_s=mean_s)
    _pos(k, v)
    _pos("shape", shape)
    if max_days is not None:
        _pos("max_days", max_days)
    return Dist(GAMMA, (v * (_DAY if k == "mean_days" else _S), float(shape),
                        (max_days or 0.0) * _DAY))


def normal(mean_h: float = 0.0, sd_h: float = 1.0) -> Dist:
    _finite("mean_h", mean_h)
    _pos("sd_h", sd_h)
    return Dist(NORMAL, (mean_h * _H, sd_h * _H, 0.0))


def pareto(alpha: float, min_h: float) -> Dist:
    _pos("alpha", alpha)
    _pos("min_h", min_h)
    return Dist(PARETO, (float(alpha), min_h * _H, 0.0))


def geometric(mean: float, max: int | None = None) -> Dist:
    if not mean >= 1:
        raise ValueError("geometric mean must be >= 1")
    _finite("mean", mean)
    if max is not None:
        _int_bound("max", max)                  # 0 = unbounded
    return Dist(GEOMETRIC, (float(mean), float(max or 0), 0.0))


def negbinom(mean: float, disp: float) -> Dist:
    _pos("mean", mean)
    _pos("disp", disp)
    return Dist(NEGBINOM, (float(mean), float(disp), 0.0))


def uniform_int(lo: int, hi: int) -> Dist:
    _int_bound("lo", lo, -_INT_LIMIT)
    _int_bound("hi", hi, -_INT_LIMIT)
    if hi < lo:
        raise ValueError("uniform_int needs lo <= hi")
    return Dist(UNIFORM_INT, (float(lo), float(hi), 0.0))


def categorical(probs: dict) -> Dist:
    if not probs:
        raise ValueError("categorical needs at least one label")
    w = tuple(_finite(f"categorical probability of {k!r}", p) for k, p in probs.items())
    if any(p < 0 for p in w):
        raise ValueError("categorical probabilities must be >= 0")
    if abs(sum(w) - 1.0) > 1e-9:
        raise ValueError("categorical probabilities must sum to 1")
    return Dist(CATEGORICAL, (float(len(w)), 0.0, 0.0), labels=tuple(probs), weights=w)


def zipf(s: float) -> Dist:
    _pos("s", s)
    return Dist(ZIPF, (float(s), 0.0, 0.0))


def poisson_daily(weekly: tuple[float, ...] = (1,) * 7, trend: float = 0.0) -> Dist:
    if len(weekly) != 7:
        raise ValueError("weekly needs 7 values")
    for x in (*weekly, trend):
        _finite("poisson_daily weekly weight / trend", x)
    if any(x < 0 for x in weekly):
        raise ValueError("weekly weights must be >= 0")
    return Dist(POISSON_DAILY, (float(trend), 0.0, 0.0),
                weights=tuple(float(x) for x in weekly))


def lognormal_minor(median: float, sigma: float, min: int | None = None,
                    max: int | None = None) -> Dist:
    _pos("median", median)
    _pos("sigma", sigma)
    lo, hi = (_int_bound(k, v or 0) for k, v in (("min", min), ("max", max)))
    if hi and hi < lo:
        raise ValueError("lognormal_minor needs min <= max")
    # bounds do not fit the 3 numeric params; carried in weights as (min, max), 0 = unbounded
    return Dist(LOGNORMAL_MINOR, (float(median), float(sigma), 0.0), weights=(lo, hi))


def encode(d: Dist) -> tuple[int, float, float, float]:
    p = d.params
    return (d.kind, p[0], p[1], p[2])


def min_us(d: Dist) -> int:
    if d.kind in (CONST, SHIFTED_LOGNORMAL):
        return int(d.params[0])
    return 0


def _normal_np(u: np.ndarray, u2: np.ndarray) -> np.ndarray:
    return np.sqrt(-2.0 * np.log1p(-u)) * np.cos(2.0 * np.pi * u2)


_NEGBINOM_MAX_TABLE = 5_000_000


def _negbinom_np(mean: float, disp: float, u: np.ndarray) -> np.ndarray:
    """Exact inverse transform of the gamma-Poisson mixture (negative binomial), log-space cdf.

    The cdf table grows until it covers max(u); a table that cannot is an error, never a clamp.
    """
    q = mean / (mean + disp)
    umax = float(u.max()) if len(u) else 0.0
    top = int(mean + 12.0 * np.sqrt(mean + mean * mean / disp) + 20.0)
    while True:
        if top > _NEGBINOM_MAX_TABLE:
            raise ValueError(f"negbinom(mean={mean}, disp={disp}) is too large to sample")
        k = np.arange(1, top + 1, dtype=np.float64)
        logp = disp * np.log1p(-q) + np.concatenate(
            ([0.0], np.cumsum(np.log(k - 1.0 + disp) - np.log(k) + np.log(q))))
        cdf = np.cumsum(np.exp(logp))
        if cdf[-1] > umax:
            return np.searchsorted(cdf, u, side="right").astype(np.int64)
        top *= 2


def sample_np(d: Dist, u: np.ndarray, u2: np.ndarray) -> np.ndarray:
    """Vectorized sampling of the count/category kinds used by static sources (int64 result)."""
    p = d.params
    if d.kind == UNIFORM_INT:
        lo, hi = int(p[0]), int(p[1])
        return lo + np.minimum((u * (hi - lo + 1)).astype(np.int64), hi - lo)
    if d.kind == CATEGORICAL:
        cum = np.cumsum(np.asarray(d.weights, np.float64))
        return np.minimum(np.searchsorted(cum, u, side="right"), len(cum) - 1).astype(np.int64)
    if d.kind == LOGNORMAL_MINOR:
        v = np.rint(np.clip(p[0] * np.exp(p[1] * _normal_np(u, u2)), 0.0, 2.0**62)).astype(np.int64)
        lo, hi = (int(w) for w in d.weights)
        if lo:
            v = np.maximum(v, lo)
        if hi:
            v = np.minimum(v, hi)
        return v
    if d.kind == NEGBINOM:
        return _negbinom_np(p[0], p[1], u)
    if d.kind == GEOMETRIC:                     # trials until first success (>= 1), as rng
        if p[0] <= 1.0:
            v = np.ones(len(u), np.int64)
        else:
            k = np.floor(np.log1p(-u) / np.log1p(-1.0 / p[0]))
            v = np.clip(k, 0.0, 2.0**62 - 1).astype(np.int64) + 1
        return np.minimum(v, int(p[1])) if p[1] else v
    if d.kind == ZIPF:
        w = 1.0 / np.arange(1, len(u) + 1, dtype=np.float64) ** p[0]
        cum = np.cumsum(w / w.sum())
        return np.minimum(np.searchsorted(cum, u, side="right"), len(u) - 1).astype(np.int64)
    raise ValueError(f"sample_np does not support distribution kind {d.kind}")
