"""Distribution descriptors. Durations are encoded in microseconds."""

from __future__ import annotations

from dataclasses import dataclass

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


def _pos(name: str, v: float) -> float:
    if not v > 0:
        raise ValueError(f"{name} must be > 0, got {v}")
    return float(v)


def _one(what: str, **kw: float | None) -> tuple[str, float]:
    given = [(k, v) for k, v in kw.items() if v is not None]
    if len(given) != 1:
        raise ValueError(f"{what}: give exactly one of {', '.join(kw)}")
    return given[0]


def constant(ms: float | None = None, s: float | None = None) -> Dist:
    k, v = _one("constant", ms=ms, s=s)
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
    _pos("sd_h", sd_h)
    return Dist(NORMAL, (mean_h * _H, sd_h * _H, 0.0))


def pareto(alpha: float, min_h: float) -> Dist:
    _pos("alpha", alpha)
    _pos("min_h", min_h)
    return Dist(PARETO, (float(alpha), min_h * _H, 0.0))


def geometric(mean: float, max: int | None = None) -> Dist:
    if not mean >= 1:
        raise ValueError("geometric mean must be >= 1")
    return Dist(GEOMETRIC, (float(mean), float(max or 0), 0.0))


def negbinom(mean: float, disp: float) -> Dist:
    _pos("mean", mean)
    _pos("disp", disp)
    return Dist(NEGBINOM, (float(mean), float(disp), 0.0))


def uniform_int(lo: int, hi: int) -> Dist:
    if hi < lo:
        raise ValueError("uniform_int needs lo <= hi")
    return Dist(UNIFORM_INT, (float(lo), float(hi), 0.0))


def categorical(probs: dict) -> Dist:
    if not probs:
        raise ValueError("categorical needs at least one label")
    w = tuple(float(p) for p in probs.values())
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
    if any(x < 0 for x in weekly):
        raise ValueError("weekly weights must be >= 0")
    return Dist(POISSON_DAILY, (float(trend), 0.0, 0.0),
                weights=tuple(float(x) for x in weekly))


def lognormal_minor(median: float, sigma: float, min: int | None = None,
                    max: int | None = None) -> Dist:
    _pos("median", median)
    _pos("sigma", sigma)
    lo, hi = float(min or 0), float(max or 0)
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
