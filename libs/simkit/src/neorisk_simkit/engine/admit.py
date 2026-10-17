"""Admission of created owners (D44): the pending-creation queue `CQ` and the free-slot rings `FS`.

`engine.route.route_outbox` appends every `OB_CREATE` outbox row to `CQ` (with `k`, the row's
ordinal within its creating commit, F-10); the generated `admit_created(W, R, CQ, FS, limit_t,
out_slots)` (`engine.codegen`) admits the due rows inside compiled rounds and in Python rounds
alike, taking local slots from `FS`. Everything here is plain arrays plus `@njit` helpers, so the
generated code can run it without leaving compiled code.

Queue tuple `CQ` (`CreationQueue.as_tuple()`, indices `CQ_*`):
  time, prio, cause, src_pid, src_seq, ns, handle, src_g, action, k   int64[C] each
  pay   int64[C, CQ_PAY]: the created row's columns (D43)
  n     int64[1]: rows queued
with `C = budget.max_admissions_per_step` (routing refuses a creation beyond it, so the queue
never overflows). `cause` is the creator's commit lamport, `ns` the namespace code of the created
table, `handle` the created row's provisional handle, `action` the creating process.

Free-slot tuple `FS` (`FreeSlots.as_tuple()`, indices `FS_*`): `(buf int32[sum of sizes],
head int64[T], n int64[T], off int64[T], cap int64[T], base int64[T])`, one FIFO ring per owner
partition type `t` (plan order) at `buf[off[t]:off[t] + cap[t]]`; `base[t]` is the type's first
global slot.
"""

from __future__ import annotations

import numpy as np
from numba import njit

# admission statuses of the generated `admit_created`
ADM_OK, ADM_CAP, ADM_LIVE, ADM_NODES = 0, 1, 2, 3
CQ_PAY = 7                       # user payload columns carried by a creation (D43)

(CQ_TIME, CQ_PRIO, CQ_CAUSE, CQ_SRC_PID, CQ_SRC_SEQ, CQ_NS, CQ_HANDLE, CQ_SRC_G, CQ_ACTION,
 CQ_K, CQ_PAYLOAD, CQ_N) = range(12)
CQ_FIELDS = ("time", "prio", "cause", "src_pid", "src_seq", "ns", "handle", "src_g", "action",
             "k")
FS_BUF, FS_HEAD, FS_N, FS_OFF, FS_CAP, FS_BASE = range(6)

_I64_MAX = np.iinfo(np.int64).max


class CreationQueue:
    """Pending creations awaiting admission (see the module docstring)."""

    row_bytes = (len(CQ_FIELDS) + CQ_PAY) * 8           # 17 * 8

    def __init__(self, capacity: int):
        self.capacity = int(capacity)
        for f in CQ_FIELDS:
            setattr(self, f, np.zeros(self.capacity, np.int64))
        self.pay = np.zeros((self.capacity, CQ_PAY), np.int64)
        self.n = np.zeros(1, np.int64)

    def as_tuple(self) -> tuple:
        return (*(getattr(self, f) for f in CQ_FIELDS), self.pay, self.n)

    def count(self) -> int:
        return int(self.n[0])


@njit(cache=True, nogil=True)
def cq_min(CQ):
    """Earliest queued creation time (I64_MAX when the queue is empty)."""
    t = CQ[CQ_TIME]
    m = np.int64(_I64_MAX)
    for i in range(CQ[CQ_N][0]):
        m = min(m, t[i])
    return m


@njit(cache=True, nogil=True)
def cq_push(CQ, time, prio, cause, src_pid, src_seq, ns, handle, src_g, action, k, pay, row):
    """Append one creation; `pay[row, :CQ_PAY]` holds its columns. The caller checked room."""
    i = CQ[CQ_N][0]
    CQ[CQ_TIME][i] = time
    CQ[CQ_PRIO][i] = prio
    CQ[CQ_CAUSE][i] = cause
    CQ[CQ_SRC_PID][i] = src_pid
    CQ[CQ_SRC_SEQ][i] = src_seq
    CQ[CQ_NS][i] = ns
    CQ[CQ_HANDLE][i] = handle
    CQ[CQ_SRC_G][i] = src_g
    CQ[CQ_ACTION][i] = action
    CQ[CQ_K][i] = k
    for c in range(CQ_PAY):
        CQ[CQ_PAYLOAD][i, c] = pay[row, c]
    CQ[CQ_N][0] = i + 1


@njit(cache=True, nogil=True)
def cq_due(CQ, limit_t):
    """Indices of the queued rows with time < limit_t, ascending."""
    n = CQ[CQ_N][0]
    t = CQ[CQ_TIME]
    out = np.empty(n, np.int64)
    m = 0
    for i in range(n):
        if t[i] < limit_t:
            out[m] = i
            m += 1
    return out[:m]


@njit(cache=True, nogil=True)
def _then_by(order, key):
    return order[np.argsort(key[order], kind="mergesort")]


@njit(cache=True, nogil=True)
def cq_order(CQ, due, keys):
    """`due` in admission order: (time, prio, cause, sender key k0..k5, src_seq) (D61), the
    order routing gives the same rows; `keys` are the creators' `route.sender_keys`."""
    k0, k1, k2, k3, k4, k5 = keys
    o = np.argsort(CQ[CQ_SRC_SEQ][due], kind="mergesort")
    o = _then_by(o, k5)
    o = _then_by(o, k4)
    o = _then_by(o, k3)
    o = _then_by(o, k2)
    o = _then_by(o, k1)
    o = _then_by(o, k0)
    o = _then_by(o, CQ[CQ_CAUSE][due])
    o = _then_by(o, CQ[CQ_PRIO][due])
    o = _then_by(o, CQ[CQ_TIME][due])
    return due[o]


@njit(cache=True, nogil=True)
def cq_remove(CQ, rows, m):
    """Drop `rows[:m]` from the queue, keeping the other rows (and their `k`) in order."""
    n = CQ[CQ_N][0]
    keep = np.ones(n, np.bool_)
    for j in range(m):
        keep[rows[j]] = False
    w = 0
    for i in range(n):
        if not keep[i]:
            continue
        if w != i:
            CQ[CQ_TIME][w] = CQ[CQ_TIME][i]
            CQ[CQ_PRIO][w] = CQ[CQ_PRIO][i]
            CQ[CQ_CAUSE][w] = CQ[CQ_CAUSE][i]
            CQ[CQ_SRC_PID][w] = CQ[CQ_SRC_PID][i]
            CQ[CQ_SRC_SEQ][w] = CQ[CQ_SRC_SEQ][i]
            CQ[CQ_NS][w] = CQ[CQ_NS][i]
            CQ[CQ_HANDLE][w] = CQ[CQ_HANDLE][i]
            CQ[CQ_SRC_G][w] = CQ[CQ_SRC_G][i]
            CQ[CQ_ACTION][w] = CQ[CQ_ACTION][i]
            CQ[CQ_K][w] = CQ[CQ_K][i]
            for c in range(CQ_PAY):
                CQ[CQ_PAYLOAD][w, c] = CQ[CQ_PAYLOAD][i, c]
        w += 1
    CQ[CQ_N][0] = w


class FreeSlots:
    """Free local slots per owner partition type: FIFO rings, initially `arange(size)`; slots
    freed at seal go to the back, sorted (exactly the S1 free-list order)."""

    def __init__(self, sizes: list[int], bases: list[int]):
        sizes = [int(s) for s in sizes]
        self.cap = np.array(sizes, np.int64)
        self.off = np.zeros(len(sizes), np.int64)
        if len(sizes):
            self.off[1:] = np.cumsum(self.cap)[:-1]
        self.base = np.array([int(b) for b in bases], np.int64)
        self.head = np.zeros(len(sizes), np.int64)
        self.cnt = self.cap.copy()
        self.buf = np.zeros(int(self.cap.sum()), np.int32)
        for t, s in enumerate(sizes):
            self.buf[self.off[t]:self.off[t] + s] = np.arange(s, dtype=np.int32)

    def n(self, t: int) -> int:
        """Free slots of type t."""
        return int(self.cnt[t])

    def _positions(self, t: int, start: int, k: int) -> np.ndarray:
        cap = int(self.cap[t])
        return self.off[t] + (start + np.arange(k, dtype=np.int64)) % max(cap, 1)

    def take(self, t: int, k: int) -> np.ndarray:
        """The first k free slots of type t (removed); IndexError if fewer are free."""
        if k > self.cnt[t]:
            raise IndexError(f"owner type {t} has {int(self.cnt[t])} free slots, not {k}")
        out = self.buf[self._positions(t, int(self.head[t]), k)].copy()
        if k:
            self.head[t] = (self.head[t] + k) % self.cap[t]
            self.cnt[t] -= k
        return out

    def give(self, t: int, lslots: np.ndarray) -> None:
        """Return slots of type t to the back of its ring, in ascending order."""
        k = len(lslots)
        if self.cnt[t] + k > self.cap[t]:
            raise AssertionError(f"owner type {t}: more slots freed than it holds")
        if k:
            pos = self._positions(t, int(self.head[t] + self.cnt[t]), k)
            self.buf[pos] = np.sort(np.asarray(lslots, np.int32))
            self.cnt[t] += k

    def as_tuple(self) -> tuple:
        return (self.buf, self.head, self.cnt, self.off, self.cap, self.base)


@njit(cache=True, nogil=True)
def fs_take1(FS, t):
    """Take the front free slot of type t; -1 when none is free."""
    n = FS[FS_N]
    if n[t] == 0:
        return np.int32(-1)
    head = FS[FS_HEAD]
    v = FS[FS_BUF][FS[FS_OFF][t] + head[t]]
    head[t] = (head[t] + 1) % FS[FS_CAP][t]
    n[t] -= 1
    return np.int32(v)
