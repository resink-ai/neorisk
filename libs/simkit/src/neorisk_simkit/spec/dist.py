"""Distributions for delays (seconds) and counts, drawn from the caller's keyed stream.

Delays may also be written as strings: "90s", "15m", "2h", "7d" (constants).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np

UNITS = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86_400.0}


def parse_duration(v: str | float) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    m = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*([smhd])\s*", v)
    if not m:
        raise ValueError(f"bad duration {v!r}; use e.g. '90s', '15m', '2h', '7d'")
    return float(m.group(1)) * UNITS[m.group(2)]


class Dist:
    def sample(self, rng: np.random.Generator) -> float:
        raise NotImplementedError


@dataclass(frozen=True)
class Const(Dist):
    value: float

    def sample(self, rng):
        return self.value


@dataclass(frozen=True)
class Exp(Dist):
    mean: float

    def sample(self, rng):
        return float(rng.exponential(self.mean))


@dataclass(frozen=True)
class LogNormal(Dist):
    median: float
    sigma: float = 1.0

    def sample(self, rng):
        return float(rng.lognormal(math.log(self.median), self.sigma))


@dataclass(frozen=True)
class Gamma(Dist):
    mean: float
    shape: float = 2.0

    def sample(self, rng):
        return float(rng.gamma(self.shape, self.mean / self.shape))


@dataclass(frozen=True)
class Uniform(Dist):
    lo: float
    hi: float

    def sample(self, rng):
        return float(rng.uniform(self.lo, self.hi))


@dataclass(frozen=True)
class Poisson(Dist):
    mean: float

    def sample(self, rng):
        return int(rng.poisson(self.mean))


@dataclass(frozen=True)
class NegBinom(Dist):
    """Counts with mean `mean` and dispersion `disp` (variance = mean + mean² / disp)."""
    mean: float
    disp: float = 1.0

    def sample(self, rng):
        p = self.disp / (self.disp + self.mean)
        return int(rng.negative_binomial(self.disp, p))


def _secs(mean_s=None, mean_m=None, mean_h=None, mean_days=None) -> float:
    for v, u in ((mean_s, 1.0), (mean_m, 60.0), (mean_h, 3600.0), (mean_days, 86_400.0)):
        if v is not None:
            return float(v) * u
    raise ValueError("give one of mean_s, mean_m, mean_h, mean_days")


def const(v: str | float) -> Const:
    return Const(parse_duration(v))


def exp(**mean) -> Exp:
    return Exp(_secs(**mean))


def lognormal(*, median_s: float | None = None, median_days: float | None = None,
              sigma: float = 1.0) -> LogNormal:
    return LogNormal(_secs(mean_s=median_s, mean_days=median_days), sigma)


def gamma(*, shape: float = 2.0, **mean) -> Gamma:
    return Gamma(_secs(**mean), shape)


def uniform(lo: str | float, hi: str | float) -> Uniform:
    return Uniform(parse_duration(lo), parse_duration(hi))


def poisson(mean: float) -> Poisson:
    return Poisson(mean)


def negbinom(mean: float, disp: float = 1.0) -> NegBinom:
    return NegBinom(mean, disp)


def draw(d: Dist | str | float | None, rng: np.random.Generator) -> float:
    """A delay or count: a Dist is sampled, a number or duration string is constant."""
    if d is None:
        return 0.0
    if isinstance(d, Dist):
        return d.sample(rng)
    return parse_duration(d)
