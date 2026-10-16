"""Calendar queue: partitions bucketed by next event time, so no step scans all owners.

Entries are (slot, time) pairs. A slot may have several entries; only the one matching the
slot's current `next_t` is valid, the rest are stale and dropped lazily during collection.

Callers collect contiguous windows `[t0, t1)` and never push a time below the end of the last
collected window (such an entry would never be emitted). A checked calendar enforces both.
"""

from __future__ import annotations

import numpy as np
from numba import njit

from neorisk_simkit.engine.errors import EngineError

_I64_MAX = np.iinfo(np.int64).max
_I64_MIN = np.iinfo(np.int64).min
# params layout: origin, bucket width, bucket count, checked flag, end of the last collected window
_ORIGIN, _WIDTH, _NB, _CHECKED, _FLOOR = 0, 1, 2, 3, 4


@njit(cache=True, nogil=True)
def _link(nxt, n):
    for i in range(n - 1):
        nxt[i] = i + 1
    if n > 0:
        nxt[n - 1] = -1


@njit(cache=True, nogil=True)
def _bucket(params, t):
    if t < params[0]:
        return 0
    b = (t - params[0]) // params[1]
    return min(b, params[2] - 1)


@njit(cache=True, nogil=True)
def cal_push(C, g, t):
    """Add an entry for slot g at time t; False when the entry pool is exhausted."""
    e_slot, e_time, e_next, free, bhead, _stamp, _epoch, params = C
    if params[3] != 0 and t < params[4]:
        raise EngineError("calendar push at ", t, " below the collected horizon ", params[4])
    e = free[0]
    if e < 0:
        return False
    free[0] = e_next[e]
    b = _bucket(params, t)
    e_slot[e] = g
    e_time[e] = t
    e_next[e] = bhead[b]
    bhead[b] = e
    return True


@njit(cache=True, nogil=True)
def cal_collect(C, next_t, t0, t1, out):
    """Write each slot with t0 <= next_t[slot] < t1 once; drop stale entries; keep later ones."""
    e_slot, e_time, e_next, free, bhead, stamp, epoch, params = C
    if t1 <= t0:
        return 0
    if params[3] != 0 and params[4] != _I64_MIN and t0 != params[4]:
        raise EngineError("calendar collect windows must be contiguous: [", t0, ", ", t1,
                          ") after a window ending at ", params[4])
    params[4] = t1
    epoch[0] += 1
    ep = epoch[0]
    n = 0
    b0 = _bucket(params, t0)
    b1 = _bucket(params, t1 - 1)
    for b in range(b0, b1 + 1):
        prev = np.int32(-1)
        e = bhead[b]
        while e >= 0:
            nx = e_next[e]
            slot = e_slot[e]
            time = e_time[e]
            drop = False
            if next_t[slot] != time:
                drop = True
            elif time >= t0 and time < t1:
                if stamp[slot] != ep:
                    stamp[slot] = ep
                    out[n] = slot
                    n += 1
                drop = True
            if drop:
                if prev < 0:
                    bhead[b] = nx
                else:
                    e_next[prev] = nx
                e_next[e] = free[0]
                free[0] = e
            else:
                prev = e
            e = nx
    return n


@njit(cache=True, nogil=True)
def _rebuild(C, next_t):
    e_slot, _t, e_next, free, bhead, _stamp, _epoch, _params = C
    n_slots = next_t.shape[0]
    had = np.zeros(n_slots, np.bool_)
    for b in range(bhead.shape[0]):
        e = bhead[b]
        while e >= 0:
            had[e_slot[e]] = True
            e = e_next[e]
    bhead[:] = -1
    _link(e_next, e_next.shape[0])
    free[0] = 0 if e_next.shape[0] else -1
    for s in range(n_slots):
        if had[s] and next_t[s] != _I64_MAX:
            cal_push(C, s, next_t[s])


class Calendar:
    def __init__(self, n_slots: int, origin_us: int, width_us: int, n_buckets: int,
                 capacity: int, checked: bool = False):
        if width_us <= 0 or n_buckets <= 0:
            raise ValueError("calendar width and bucket count must be positive")
        self.n_slots = n_slots
        self.e_slot = np.zeros(capacity, np.int32)
        self.e_time = np.zeros(capacity, np.int64)
        self.e_next = np.full(capacity, -1, np.int32)
        _link(self.e_next, capacity)
        self.free = np.array([0 if capacity else -1], np.int32)
        self.bhead = np.full(n_buckets, -1, np.int32)
        self.stamp = np.zeros(n_slots, np.int64)
        self.epoch = np.zeros(1, np.int64)
        self.params = np.array([origin_us, width_us, n_buckets, int(checked), _I64_MIN],
                               np.int64)

    def as_tuple(self) -> tuple:
        return (self.e_slot, self.e_time, self.e_next, self.free, self.bhead, self.stamp,
                self.epoch, self.params)

    def compact(self, next_t: np.ndarray) -> None:
        """Rebuild from next_t: one entry per slot that had an entry and has a finite next_t."""
        _rebuild(self.as_tuple(), next_t)
