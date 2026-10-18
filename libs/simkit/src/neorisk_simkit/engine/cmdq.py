"""Per-partition command queues over a shared node pool, plus the payload arena.

A command node is `NODE_BYTES` (D8 amended by D61). Each partition's queue is a singly linked
list sorted by (time, key, sender key, seq) with key = priority << 56 | cause_lamport (D9).

The sender key (D61) makes a shard's order of tied commands independent of the round in which
they arrived (spec section 12, canonical processing in shards). A delivered request, message or
response carries its sender's step-invariant key `(ptype << 1 | created, pid or created_at,
creator lamport, creator inst, k)` (`engine.route.sender_keys`) and, in `seq`, the sender's own
command seq (`src_seq`). A command a partition queues for itself (timer, continuation, START)
carries `SELF_SENDER` (-1, so it runs before tied delivered commands) and its own `cseq` value.
The sender key plus seq is unique within a queue, so the order is total and exact.

Free nodes live in per-worker lists so hot-path pushes and frees never contend; a global reserve
list feeds worker refills.
"""

from __future__ import annotations

import numpy as np
from numba import njit

PAYLOAD_W = 12          # cols 0..6 user payload, 7 src_g, 8 src_gen, 9 src_self_id, 10 src_action,
#                         11 PAY_KIND
# payload column 11: in the outbox, a response's requester generation; once delivered, the
# delivered kind (D39)
PAY_KIND = 11
PAY_CONTINUE = -2       # n_pay marker: the node is a continuation and n_tag is its cursor

# Positions in `NodePool.as_tuple()` that generated code reads (the worker free lists).
P_FREE_HEAD = 8
P_FREE_N = 9
P_SK0, P_SK1, P_SK2, P_SK3, P_SK4 = 10, 11, 12, 13, 14     # the sender key fields
P_CPID, P_CEID = 15, 16                                     # the cause fields (D80)

# `ceid` of a command node (D80): the event id of its cause once seal resolved it, `NULL_CAUSE`
# when it has none (a population or periodic START, or a chain without an exported event), or
# `UNSET_CAUSE` while its cause is the commit (`cpid`, cause lamport) of the running step. Every
# writer of a node sets `cpid` and `ceid` right after a successful push.
UNSET_CAUSE, NULL_CAUSE = -2, -1

SELF_SENDER = -1        # sender key part 0 of a command a partition queues for itself

# (field, dtype) of a command node, in `NodePool.as_tuple()` order (free lists excluded)
NODE_FIELDS = (("time", "int64"), ("key", "int64"), ("seq", "int64"), ("tag", "int64"),
               ("next", "int32"), ("kind", "int16"), ("proc", "int16"), ("pay", "int32"),
               ("sk0", "int16"), ("sk1", "int64"), ("sk2", "int64"), ("sk3", "int64"),
               ("sk4", "int32"), ("cpid", "int64"), ("ceid", "int64"))
NODE_BYTES = sum(np.dtype(dt).itemsize for _, dt in NODE_FIELDS)

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

    def release(self, worker: int, n: int) -> None:
        """Move the first n nodes of `worker`'s free list back to the reserve."""
        if n < 0 or self.free_n[worker] < n:
            raise ValueError(f"worker {worker} holds {int(self.free_n[worker])} nodes, not {n}")
        if n:
            _move(self._nxt, self.free_head, self.free_n, worker,
                  self.reserve_head, self.reserve_n, 0, n)

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
        self.sk0 = np.zeros(capacity, np.int16)
        self.sk1 = np.zeros(capacity, np.int64)
        self.sk2 = np.zeros(capacity, np.int64)
        self.sk3 = np.zeros(capacity, np.int64)
        self.sk4 = np.zeros(capacity, np.int32)
        self.cpid = np.zeros(capacity, np.int64)     # partition id of the causing commit
        self.ceid = np.full(capacity, NULL_CAUSE, np.int64)
        self._init_lists(self.next, capacity, workers)

    def as_tuple(self) -> tuple:
        return self.with_free_lists(self.free_head, self.free_n)

    def with_free_lists(self, head: np.ndarray, n: np.ndarray) -> tuple:
        """The pool tuple with `(head, n)` as the free lists (the reserve, for routing)."""
        return (self.time, self.key, self.seq, self.tag, self.next, self.kind, self.proc,
                self.pay, head, n, self.sk0, self.sk1, self.sk2, self.sk3, self.sk4,
                self.cpid, self.ceid)


class PayloadPool(_FreeLists):
    def __init__(self, capacity: int, workers: int):
        self.rows = np.zeros((capacity, PAYLOAD_W), np.int64)
        self._free_next = np.full(capacity, -1, np.int32)
        self._init_lists(self._free_next, capacity, workers)

    def as_tuple(self) -> tuple:
        return (self.rows, self._free_next, self.free_head, self.free_n)


@njit(cache=True, nogil=True)
def q_push(P, w, qhead, g, time, prio, cause, seq, kind, proc, tag, pay):
    """Queue a command slot g issues for itself (sender `SELF_SENDER`); see `q_push_from`."""
    return q_push_from(P, w, qhead, g, time, prio, cause, seq, kind, proc, tag, pay,
                       SELF_SENDER, 0, 0, 0, 0)


@njit(cache=True, nogil=True)
def _after(P, cur, key, s0, s1, s2, s3, s4, seq):
    """Whether node `cur` (same time) sorts after (key, s0..s4, seq): lexicographic, exact."""
    if P[1][cur] != key:
        return P[1][cur] > key
    if P[P_SK0][cur] != s0:
        return P[P_SK0][cur] > s0
    if P[P_SK1][cur] != s1:
        return P[P_SK1][cur] > s1
    if P[P_SK2][cur] != s2:
        return P[P_SK2][cur] > s2
    if P[P_SK3][cur] != s3:
        return P[P_SK3][cur] > s3
    if P[P_SK4][cur] != s4:
        return P[P_SK4][cur] > s4
    return P[2][cur] > seq


@njit(cache=True, nogil=True)
def q_push_from(P, w, qhead, g, time, prio, cause, seq, kind, proc, tag, pay, s0, s1, s2, s3,
                s4):
    """Insert a command into slot g's queue in (time, key, sender key s0..s4, seq) order; -1
    when worker w has no free node. `seq` is the sender's own command seq."""
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
    P[P_SK0][node] = s0
    P[P_SK1][node] = s1
    P[P_SK2][node] = s2
    P[P_SK3][node] = s3
    P[P_SK4][node] = s4
    prev = np.int32(-1)
    cur = qhead[g]
    while cur >= 0:
        ct = P[0][cur]
        if ct > time:
            break
        if ct == time and _after(P, cur, key, s0, s1, s2, s3, s4, seq):
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
