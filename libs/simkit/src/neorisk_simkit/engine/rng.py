"""Keyed counter-based RNG: every draw is a pure function of (seed, instance, action, occurrence,
site, k), so retries and thread counts never change results."""

from __future__ import annotations

import hashlib
import math

import numpy as np
from numba import njit, uint64
from numba.extending import overload

from neorisk_simkit.spec.dist import (
    CONST,
    EXP,
    GAMMA,
    LOGNORMAL,
    NORMAL,
    PARETO,
    SHIFTED_LOGNORMAL,
)

MASK64 = 0xFFFF_FFFF_FFFF_FFFF
_GOLD = np.uint64(0x9E3779B97F4A7C15)
_MAX_SITES = 16
_TWO_PI = 2.0 * math.pi
_MAX_US = 4.611686018427388e18          # 2^62: keeps float -> int64 casts defined


def u64(x):
    """Wrap-around cast to uint64; used as-is when NUMBA_DISABLE_JIT=1."""
    return np.uint64(int(x) & MASK64)


@overload(u64)
def _u64_jit(x):
    return lambda x: uint64(x)


def mul64(a, b):
    """Wrap-around uint64 multiply (silences NumPy's scalar overflow warning when uncompiled)."""
    with np.errstate(over="ignore"):
        return np.uint64(a) * np.uint64(b)


@overload(mul64)
def _mul64_jit(a, b):
    return lambda a, b: uint64(a) * uint64(b)


def add64(a, b):
    with np.errstate(over="ignore"):
        return np.uint64(a) + np.uint64(b)


@overload(add64)
def _add64_jit(a, b):
    return lambda a, b: uint64(a) + uint64(b)


@njit(cache=True, nogil=True)
def mix64(x):
    x = u64(x)
    x = mul64(x ^ (x >> uint64(30)), uint64(0xBF58476D1CE4E5B9))
    x = mul64(x ^ (x >> uint64(27)), uint64(0x94D049BB133111EB))
    return x ^ (x >> uint64(31))


def mix(*parts: int) -> int:
    """Python-side keyed mix of any number of ints (each masked to 64 bits); unsigned result."""
    h = 0
    for p in parts:
        h = int(mix64(np.uint64((h ^ (p & MASK64)) & MASK64)))
    return h


def name_key(name: str) -> int:
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "little")


@njit(cache=True, nogil=True)
def key_uniform(seed, inst, action, occ, site, k):
    h = mix64(add64(u64(seed), _GOLD))
    h = mix64(h ^ u64(inst))
    h = mix64(h ^ (u64(action) << uint64(32)) ^ u64(site))
    h = mix64(h ^ u64(occ))
    h = mix64(h ^ u64(k))
    return (h >> uint64(11)) * (1.0 / 9007199254740992.0)    # 53 bits -> [0, 1)


@njit(cache=True, nogil=True)
def next_k(kc, site):
    """Return and advance the draw counter of `site`; kc = [pairs_used, site0, k0, site1, k1...]."""
    n = kc[0]
    for i in range(n):
        if kc[1 + 2 * i] == site:
            k = kc[2 + 2 * i]
            kc[2 + 2 * i] = k + 1
            return k
    if n >= _MAX_SITES:
        raise ValueError("more than 16 sites")
    kc[1 + 2 * n] = site
    kc[2 + 2 * n] = 1
    kc[0] = n + 1
    return 0


@njit(cache=True, nogil=True)
def normal(u1, u2):
    """Standard normal by Box-Muller from a uniform pair."""
    return math.sqrt(-2.0 * math.log(1.0 - u1)) * math.cos(_TWO_PI * u2)


@njit(cache=True, nogil=True)
def pareto_us(alpha, min_us, u):
    return min_us * (1.0 - u) ** (-1.0 / alpha)


@njit(cache=True, nogil=True)
def sample_us(code, p1, p2, p3, u1, u2):
    """Duration in microseconds for the encoded duration distribution (see dist.encode)."""
    if code == CONST:
        v = p1
    elif code == EXP:
        v = -p1 * math.log(1.0 - u1)
    elif code == LOGNORMAL:
        v = p1 * math.exp(p2 * normal(u1, u2))
    elif code == SHIFTED_LOGNORMAL:
        v = p1 + p2 * math.exp(p3 * normal(u1, u2))
    elif code == GAMMA:
        a = 1.0 / (9.0 * p2)                       # Wilson-Hilferty approximation
        c = 1.0 - a + normal(u1, u2) * math.sqrt(a)
        v = p1 * c * c * c if c > 0.0 else 0.0
        if p3 > 0.0 and v > p3:
            v = p3
    elif code == NORMAL:
        v = p1 + p2 * normal(u1, u2)
    elif code == PARETO:
        v = pareto_us(p1, p2, u1)
    else:
        raise ValueError("not a duration distribution")
    return np.int64(np.rint(min(max(v, 0.0), _MAX_US)))


@njit(cache=True, nogil=True)
def geometric(mean, u):
    """Trials until first success (>= 1) with the given mean."""
    if mean <= 1.0:
        return np.int64(1)
    return np.int64(math.floor(math.log(1.0 - u) / math.log(1.0 - 1.0 / mean))) + 1


@njit(cache=True, nogil=True)
def bernoulli(p, u):
    return u < p


@njit(cache=True, nogil=True)
def uniform_int(lo, hi, u):
    return np.int64(lo) + np.int64(u * (hi - lo + 1))


@njit(cache=True, nogil=True)
def categorical(weights, u):
    acc = 0.0
    last = len(weights) - 1
    for i in range(last):
        acc += weights[i]
        if u < acc:
            return np.int64(i)
    return np.int64(last)


@njit(cache=True, nogil=True)
def _fill_uniforms(seed, stream, offset, out):
    for i in range(out.shape[0]):
        out[i] = key_uniform(seed, stream, 0, 0, 0, add64(u64(offset), u64(i)))


def uniforms(seed: int, stream: int, n: int, offset: int = 0) -> np.ndarray:
    """n keyed uniforms: key_uniform(seed, stream, 0, 0, 0, offset + i)."""
    out = np.empty(n, np.float64)
    _fill_uniforms(np.uint64(seed & MASK64), np.uint64(stream & MASK64), offset, out)
    return out
