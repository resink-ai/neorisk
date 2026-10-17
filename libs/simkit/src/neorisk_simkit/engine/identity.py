"""Provisional handles and seeded Feistel public IDs (spec section 12)."""

from __future__ import annotations

import numpy as np
from numba import int64, njit, uint64

from neorisk_simkit.engine.rng import MASK64, mix, mix64, name_key, u64

FLAG = 1 << 62
NS_BITS = 6                                 # D11: namespace code width in a provisional handle
MAX_NAMESPACES = 1 << NS_BITS               # created tables + p.ids namespaces (spec.validate)
_DOMAIN = (1 << 63) - 1                     # dense indices live in [0, 2^63 - 1)
_LOW32 = 0xFFFFFFFF


@njit(cache=True, nogil=True)
def make_handle(ns, slot, ordinal):
    """bit 62 | ns (6 bits) << 56 | global slot (32 bits) << 24 | per-step ordinal (24 bits)."""
    return int64(FLAG | (ns << 56) | (slot << 24) | ordinal)


@njit(cache=True, nogil=True)
def handle_ns(h):
    return (h >> 56) & 63


@njit(cache=True, nogil=True)
def handle_slot(h):
    return (h >> 24) & _LOW32


@njit(cache=True, nogil=True)
def handle_ordinal(h):
    return h & 0xFFFFFF


@njit(cache=True, nogil=True)
def is_provisional(v):
    return v >= 0 and (v & FLAG) != 0


def feistel_key(seed: int, name: str) -> np.ndarray:
    """Four round keys for the table `name` under `seed`."""
    base = (seed & MASK64) ^ name_key(name)
    return np.array([mix((base ^ i) & MASK64) for i in range(4)], dtype=np.uint64)


@njit(cache=True, nogil=True)
def feistel63(dense, keys):
    """Bijection [0, 2^63 - 1) -> [1, 2^63 - 1]: 4-round Feistel on 64 bits with cycle walking."""
    if dense < 0 or dense >= _DOMAIN:
        raise ValueError("feistel63 input outside the domain [0, 2^63 - 1)")
    x = u64(dense)
    limit = uint64(_DOMAIN)
    while True:
        left = x >> uint64(32)
        right = x & uint64(_LOW32)
        for i in range(4):
            left, right = right, left ^ (mix64(right ^ keys[i]) & uint64(_LOW32))
        x = (left << uint64(32)) | right
        if x < limit:
            return int64(x) + 1


@njit(cache=True, nogil=True)
def feistel63_array(dense, keys):
    out = np.empty(dense.shape[0], np.int64)
    for i in range(dense.shape[0]):
        out[i] = feistel63(dense[i], keys)
    return out


def assign_dense(pids: np.ndarray, ordinals: np.ndarray, base: int) -> np.ndarray:
    """Dense value per row: `base` + rank of the row by (pid, ordinal)."""
    order = np.lexsort((ordinals, pids))
    out = np.empty(len(pids), np.int64)
    out[order] = base + np.arange(len(pids), dtype=np.int64)
    return out


def remap_inplace(values: np.ndarray, src_sorted: np.ndarray, dst: np.ndarray) -> int:
    """Replace provisional values found in `src_sorted` by the matching `dst`; return misses."""
    idx = np.flatnonzero((values >= 0) & ((values & FLAG) != 0))
    if len(idx) == 0:
        return 0
    vals = values[idx]
    pos = np.minimum(np.searchsorted(src_sorted, vals), max(len(src_sorted) - 1, 0))
    found = (src_sorted[pos] == vals) if len(src_sorted) else np.zeros(len(vals), bool)
    values[idx[found]] = dst[pos[found]]
    return int(len(vals) - found.sum())
