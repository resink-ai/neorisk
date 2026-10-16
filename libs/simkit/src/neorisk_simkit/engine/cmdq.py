"""Per-partition command queues over a shared node pool, plus the payload arena.

A command node is 40 B (D8). Each partition's queue is a singly linked list sorted by
(time, key, seq) with key = priority << 56 | cause_lamport (D9). Free nodes live in per-worker
lists so hot-path pushes and frees never contend; a global reserve list feeds worker refills.
"""

from __future__ import annotations

import numpy as np
from numba import njit

PAYLOAD_W = 12          # cols 0..6 user payload, 7 src_g, 8 src_gen, 9 src_self_id, 10 src_action
PAY_CONTINUE = -2       # n_pay marker: the node is a continuation and n_tag is its cursor

# Positions in `NodePool.as_tuple()` that generated code reads (the worker free lists).
P_FREE_HEAD = 8
P_FREE_N = 9

_PRIO_MAX = 63
_CAUSE_LIMIT = 1 << 56


@njit(cache=True, nogil=True)
def pack_key(prio, cause):
    if prio < 0 or prio > 63:
        raise ValueError("priority out of range")
    if cause < 0 or cause >= (1 << 56):
        raise ValueError("cause_lamport out of range")
    return (np.int64(prio) << 56) | np.int64(cause)


@njit(cache=True, nogil=True)
def _link_chain(nxt, n):
    for i in range(n - 1):
        nxt[i] = i + 1
    if n > 0:
        nxt[n - 1] = -1


@njit(cache=True, nogil=True)
def _move(nxt, src_head, src_n, w, dst_head, dst_n, dw, n):
    """Move the first n nodes of list src (slot w) to the front of list dst (slot dw)."""
    first = src_head[w]
    last = first
    for _ in range(n - 1):
        last = nxt[last]
    src_head[w] = nxt[last]
    src_n[w] -= n
    nxt[last] = dst_head[dw]
    dst_head[dw] = first
    dst_n[dw] += n


@njit(cache=True, nogil=True)
def _splice(nxt, free_head, free_n, res_head, res_n):
    for w in range(free_head.shape[0]):
        if free_n[w] > 0:
            tail = free_head[w]
            while nxt[tail] >= 0:
                tail = nxt[tail]
            nxt[tail] = res_head[0]
            res_head[0] = free_head[w]
            res_n[0] += free_n[w]
            free_head[w] = -1
            free_n[w] = 0


class _FreeLists:
    """Per-worker free lists over a `next` array, backed by one reserve list."""

    capacity: int
    workers: int

    def _init_lists(self, nxt: np.ndarray, capacity: int, workers: int) -> None:
        self.capacity = capacity
        self.workers = workers
        self._nxt = nxt
        _link_chain(nxt, capacity)
        self.free_head = np.full(workers, -1, np.int32)
        self.free_n = np.zeros(workers, np.int64)
        self.reserve_head = np.array([0 if capacity else -1], np.int32)
        self.reserve_n = np.array([capacity], np.int64)

    def refill(self, worker: int, n: int) -> bool:
        """Move n nodes from the reserve to `worker`; False (and no change) if too few."""
        if n < 0 or self.reserve_n[0] < n:
            return False
        if n:
            _move(self._nxt, self.reserve_head, self.reserve_n, 0,
                  self.free_head, self.free_n, worker, n)
        return True

    def splice_all(self) -> None:
        """Return every worker's free list to the reserve."""
        _splice(self._nxt, self.free_head, self.free_n, self.reserve_head, self.reserve_n)

    def in_use(self) -> int:
        return int(self.capacity - self.reserve_n[0] - self.free_n.sum())


class NodePool(_FreeLists):
    def __init__(self, capacity: int, workers: int):
        self.time = np.zeros(capacity, np.int64)
        self.key = np.zeros(capacity, np.int64)
        self.seq = np.zeros(capacity, np.int64)
        self.tag = np.zeros(capacity, np.int64)
        self.next = np.full(capacity, -1, np.int32)
        self.kind = np.zeros(capacity, np.int16)
        self.proc = np.zeros(capacity, np.int16)
        self.pay = np.full(capacity, -1, np.int32)
        self._init_lists(self.next, capacity, workers)

    def as_tuple(self) -> tuple:
        return (self.time, self.key, self.seq, self.tag, self.next, self.kind, self.proc,
                self.pay, self.free_head, self.free_n)


class PayloadPool(_FreeLists):
    def __init__(self, capacity: int, workers: int):
        self.rows = np.zeros((capacity, PAYLOAD_W), np.int64)
        self._free_next = np.full(capacity, -1, np.int32)
        self._init_lists(self._free_next, capacity, workers)

    def as_tuple(self) -> tuple:
        return (self.rows, self._free_next, self.free_head, self.free_n)


@njit(cache=True, nogil=True)
def q_push(P, w, qhead, g, time, prio, cause, seq, kind, proc, tag, pay):
    """Insert a command into slot g's queue; -1 when worker w has no free node."""
    key = pack_key(prio, cause)
    free_head = P[P_FREE_HEAD]
    node = free_head[w]
    if node < 0:
        return np.int32(-1)
    nxt = P[4]
    free_head[w] = nxt[node]
    P[P_FREE_N][w] -= 1
    P[0][node] = time
    P[1][node] = key
    P[2][node] = seq
    P[3][node] = tag
    P[5][node] = kind
    P[6][node] = proc
    P[7][node] = pay
    prev = np.int32(-1)
    cur = qhead[g]
    while cur >= 0:
        ct = P[0][cur]
        if ct > time:
            break
        if ct == time:
            ck = P[1][cur]
            if ck > key or (ck == key and P[2][cur] > seq):
                break
        prev = cur
        cur = nxt[cur]
    nxt[node] = cur
    if prev < 0:
        qhead[g] = node
    else:
        nxt[prev] = node
    return node


@njit(cache=True, nogil=True)
def q_peek(P, qhead, g):
    return qhead[g]


@njit(cache=True, nogil=True)
def q_pop(P, qhead, g):
    """Unlink and return the head node of slot g's queue (-1 when empty)."""
    node = qhead[g]
    if node >= 0:
        qhead[g] = P[4][node]
        P[4][node] = -1
    return node


@njit(cache=True, nogil=True)
def q_remove(P, qhead, g, node):
    """Unlink `node` from slot g's queue wherever it sits (usually the head)."""
    nxt = P[4]
    cur = qhead[g]
    if cur == node:
        qhead[g] = nxt[node]
    else:
        while cur >= 0 and nxt[cur] != node:
            cur = nxt[cur]
        if cur < 0:
            raise ValueError("q_remove: node is not in the queue")
        nxt[cur] = nxt[node]
    nxt[node] = -1


@njit(cache=True, nogil=True)
def q_free(P, w, node):
    P[4][node] = P[P_FREE_HEAD][w]
    P[P_FREE_HEAD][w] = node
    P[P_FREE_N][w] += 1


@njit(cache=True, nogil=True)
def pay_alloc(PA, w):
    head = PA[2]
    row = head[w]
    if row < 0:
        return np.int32(-1)
    head[w] = PA[1][row]
    PA[3][w] -= 1
    return row


@njit(cache=True, nogil=True)
def pay_free(PA, w, row):
    PA[1][row] = PA[2][w]
    PA[2][w] = row
    PA[3][w] += 1
