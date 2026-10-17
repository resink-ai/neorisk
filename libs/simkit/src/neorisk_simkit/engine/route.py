"""Routing between rounds: outbox rows to receiving queues, and the safe horizon (D5).

Every function here is `@njit` so the generated `drain_small_rounds` (D4) runs whole rounds in
compiled code; `engine.world.World` builds the route tuple `R` and calls the same functions
between Python phases. Routing only runs between phases (no worker is executing), so it takes
command nodes and payload rows straight from the reserve lists of the node and payload pools
(`R[RT_POOL]`, `R[RT_PAY]`); it never allocates anything itself — `route_outbox` checks the
reserves first and reports a shortfall before touching any queue (all or nothing).

Route tuple `R` (indices `RT_*`):
  qhead, cseq, gen, alive, pending, susp_t, susp_delta   hidden arrays (length G)
  pool      node pool tuple with the reserve list in place of a worker free list (worker 0)
  pay       payload pool tuple with the reserve list in place of a worker free list
  bnd_base  int64[boundaries]: global slot of shard 0 of each boundary's target partition
  counters  int64[workers, len(COUNTERS)] (late messages are counted in row 0)
  msg       int64[2]: messages routed this step, `engine.max_messages_per_step`
  woken     int64[G] + woken_n int64[1]: owners whose `pending` dropped to 0
  tmask     uint8[G] + tlist int64[G] + tn int64[1]: slots touched this step
  susp      int64[G] + susp_n int64[1] + smask uint8[G]: the suspended owners (pending > 0)
            as a min-heap on susp_t + delta, each listed once (see `note_suspended`)
  bnd_req   int64[boundaries]: requests delivered per boundary code over the run (run stats)
  spos      int64[G]: heap position of each listed suspended owner
"""

from __future__ import annotations

import numpy as np
from numba import njit

from neorisk_simkit.engine.cmdq import P_FREE_N, PAYLOAD_W, pay_alloc, q_push
from neorisk_simkit.engine.codegen import COUNTERS
from neorisk_simkit.engine.slabs import OB_CREATE, OB_REQUEST, OB_RESPONSE, OUTBOX_COLS

(RT_QHEAD, RT_CSEQ, RT_GEN, RT_ALIVE, RT_PENDING, RT_SUSP_T, RT_SUSP_DELTA, RT_POOL, RT_PAY,
 RT_BND_BASE, RT_COUNTERS, RT_MSG, RT_WOKEN, RT_WOKEN_N, RT_TMASK, RT_TLIST, RT_TN, RT_SUSP,
 RT_SUSP_N, RT_SMASK, RT_BND_REQ, RT_SPOS) = range(22)

# route_outbox statuses
ROUTED, NEED_MESSAGES, NEED_NODES, NEED_PAYLOAD, HAS_CREATE = 0, 1, 2, 3, 4

_OB = {c: i for i, c in enumerate(OUTBOX_COLS)}
_KIND, _BND, _TIME, _PRIO, _CAUSE = (_OB["kind"], _OB["bnd"], _OB["time"], _OB["prio"],
                                     _OB["cause"])
_SRC_PID, _SRC_SEQ, _DST, _TAG = _OB["src_pid"], _OB["src_seq"], _OB["dst"], _OB["tag"]
_RESP_KIND, _TARGET = _OB["resp_kind"], _OB["target_action"]
_PAYC = len(OUTBOX_COLS)
_LATE = COUNTERS.index("late_messages")
_CMDS = COUNTERS.index("commands")
_I64_MAX = np.iinfo(np.int64).max


@njit(cache=True, nogil=True)
def safe_horizon(step_end, susp_t, susp_delta, create_t):
    """H = min(step end, min over suspended owners of (susp_t + delta), min creation time)."""
    h = np.int64(step_end)
    for i in range(susp_t.shape[0]):
        if susp_t[i] < _I64_MAX - susp_delta[i]:          # saturating: never wraps negative
            h = min(h, susp_t[i] + susp_delta[i])
    for i in range(create_t.shape[0]):
        h = min(h, create_t[i])
    return h


@njit(cache=True, nogil=True)
def mark_touched(R, g):
    tmask = R[RT_TMASK]
    if tmask[g] == 0:
        tmask[g] = 1
        tn = R[RT_TN]
        R[RT_TLIST][tn[0]] = g
        tn[0] += 1


@njit(cache=True, nogil=True)
def mark_all(R, slots, n):
    for i in range(n):
        mark_touched(R, slots[i])


@njit(cache=True, nogil=True)
def _wake_key(R, g):
    """susp_t + delta of suspended owner g, saturating (the term it adds to the horizon)."""
    t, d = R[RT_SUSP_T][g], R[RT_SUSP_DELTA][g]
    return t + d if t < _I64_MAX - d else _I64_MAX


@njit(cache=True, nogil=True)
def _heap_swap(R, i, j):
    heap, pos = R[RT_SUSP], R[RT_SPOS]
    a, b = heap[i], heap[j]
    heap[i], heap[j] = b, a
    pos[b], pos[a] = i, j


@njit(cache=True, nogil=True)
def _heap_up(R, i):
    heap = R[RT_SUSP]
    while i > 0:
        parent = (i - 1) // 2
        if _wake_key(R, heap[parent]) <= _wake_key(R, heap[i]):
            break
        _heap_swap(R, i, parent)
        i = parent


@njit(cache=True, nogil=True)
def _heap_down(R, i):
    heap, n = R[RT_SUSP], R[RT_SUSP_N][0]
    while True:
        lo, c = i, 2 * i + 1
        if c < n and _wake_key(R, heap[c]) < _wake_key(R, heap[lo]):
            lo = c
        if c + 1 < n and _wake_key(R, heap[c + 1]) < _wake_key(R, heap[lo]):
            lo = c + 1
        if lo == i:
            return
        _heap_swap(R, i, lo)
        i = lo


@njit(cache=True, nogil=True)
def _unlist_suspended(R, g):
    """Remove owner g from the suspended heap (no-op if it is not listed)."""
    smask = R[RT_SMASK]
    if smask[g] == 0:
        return
    smask[g] = 0
    heap, sn, pos = R[RT_SUSP], R[RT_SUSP_N], R[RT_SPOS]
    i = pos[g]
    last = sn[0] - 1
    sn[0] = last
    if i != last:
        moved = heap[last]
        heap[i] = moved
        pos[moved] = i
        _heap_up(R, i)
        _heap_down(R, pos[moved])


@njit(cache=True, nogil=True)
def note_suspended(R, slots, n):
    """After an owner phase over `slots[:n]`: mark them touched, list the suspended ones.

    The suspended owners are a binary min-heap on susp_t + delta (`RT_SUSP[:RT_SUSP_N]`, slot
    positions in `RT_SPOS`, membership in `RT_SMASK`), each listed once; routing unlists an
    owner when its last response is delivered, so the horizon costs O(1) per round instead of
    a scan over every suspended owner."""
    heap, sn, pending, smask, pos = (R[RT_SUSP], R[RT_SUSP_N], R[RT_PENDING], R[RT_SMASK],
                                     R[RT_SPOS])
    for i in range(n):
        g = slots[i]
        mark_touched(R, g)
        if pending[g] > 0 and smask[g] == 0:
            smask[g] = 1
            k = sn[0]
            heap[k] = g
            pos[g] = k
            sn[0] = k + 1
            _heap_up(R, k)


@njit(cache=True, nogil=True)
def horizon(R, step_end, create_min):
    """`safe_horizon` over the owners still waiting for a response (the heap's top)."""
    heap, sn, pending = R[RT_SUSP], R[RT_SUSP_N], R[RT_PENDING]
    while sn[0] > 0 and pending[heap[0]] == 0:     # defensive: unlisted on delivery already
        _unlist_suspended(R, heap[0])
    h = min(np.int64(step_end), np.int64(create_min))
    if sn[0] > 0:
        h = min(h, _wake_key(R, heap[0]))
    return h


@njit(cache=True, nogil=True)
def shards_below(R, lo, hi, limit, out):
    """Shard slots in [lo, hi) whose next command is before `limit`, into `out`; the count."""
    qhead, ptime = R[RT_QHEAD], R[RT_POOL][0]
    n = 0
    for g in range(lo, hi):
        node = qhead[g]
        if node >= 0 and ptime[node] < limit:
            out[n] = g
            n += 1
    return n


@njit(cache=True, nogil=True)
def take_runnable(R, t1, out):
    """Woken owners with nothing pending and a command before t1, sorted, into `out`."""
    woken, wn = R[RT_WOKEN], R[RT_WOKEN_N]
    qhead, pending, ptime = R[RT_QHEAD], R[RT_PENDING], R[RT_POOL][0]
    n = 0
    for i in range(wn[0]):
        g = woken[i]
        node = qhead[g]
        if pending[g] == 0 and node >= 0 and ptime[node] < t1:
            out[n] = g
            n += 1
    wn[0] = 0
    out[:n].sort()
    return n


@njit(cache=True, nogil=True)
def command_count(counters):
    return counters[:, _CMDS].sum()


@njit(cache=True, nogil=True)
def _append(nxt, heads, tails, k, node):
    if tails[k] < 0:
        heads[k] = node
    else:
        nxt[tails[k]] = node
    tails[k] = node


@njit(cache=True, nogil=True)
def resume_owner(P, qhead, g):
    """Blocking suspension: the owner resumes at T_r, the latest time among its delivered
    responses, and runs nothing dated before it. Its queue becomes: the responses, then the
    other commands dated before T_r, then those dated exactly T_r (each group in its (time,
    key, seq) order), all re-dated to T_r — the effective time max(time, T_r) — then the rest.
    The queue stays sorted by time.

    In S1 an owner receives only responses, so its payload-carrying nodes are the responses.
    """
    ptime, nxt, ppay = P[0], P[4], P[7]
    t_r = np.int64(-(2 ** 63))
    node = qhead[g]
    while node >= 0:
        if ppay[node] >= 0:
            t_r = max(t_r, ptime[node])
        node = nxt[node]
    heads = np.full(3, -1, np.int32)      # 0 responses, 1 earlier commands, 2 commands at t_r
    tails = np.full(3, -1, np.int32)
    node = qhead[g]
    while node >= 0 and ptime[node] <= t_r:
        nx = nxt[node]
        nxt[node] = -1
        k = 0 if ppay[node] >= 0 else (1 if ptime[node] < t_r else 2)
        ptime[node] = t_r
        _append(nxt, heads, tails, k, node)
        node = nx
    rest = node
    for k in range(2, -1, -1):
        if tails[k] >= 0:
            nxt[tails[k]] = rest
            rest = heads[k]
    qhead[g] = rest


@njit(cache=True, nogil=True)
def route_order(ob, n):
    """Row order by (time, prio, cause, src_pid, src_seq): stable sorts, last key first."""
    order = np.argsort(ob[_SRC_SEQ][:n], kind="mergesort")
    order = order[np.argsort(ob[_SRC_PID][:n][order], kind="mergesort")]
    order = order[np.argsort(ob[_CAUSE][:n][order], kind="mergesort")]
    order = order[np.argsort(ob[_PRIO][:n][order], kind="mergesort")]
    return order[np.argsort(ob[_TIME][:n][order], kind="mergesort")]


@njit(cache=True, nogil=True)
def route_outbox(R, ob, n, skip_creates):
    """Deliver the first n rows of outbox `ob` (`OUTBOX_COLS` then `pay`); (status, rows).

    Requests go to the shard queue at the request time, messages to the shard queue at their
    delivery time, responses to the requesting owner if its slot generation still matches
    (then `pending -= 1`; otherwise `late_messages += 1`). Every delivered command gets a
    payload row copied from the outbox and the receiver's next command seq. `OB_CREATE` rows
    are left to the caller (`skip_creates`), or make the call return `HAS_CREATE` untouched.
    Nothing is delivered unless the step's message budget and both reserves cover every row.
    """
    kinds = ob[_KIND]
    k = np.int64(0)
    for i in range(n):
        if kinds[i] == OB_CREATE:
            if not skip_creates:
                return HAS_CREATE, k
        else:
            k += 1
    msg = R[RT_MSG]
    if msg[0] + k > msg[1]:
        return NEED_MESSAGES, msg[0] + k
    P, PA = R[RT_POOL], R[RT_PAY]
    if P[P_FREE_N][0] < k:
        return NEED_NODES, k
    if PA[3][0] < k:
        return NEED_PAYLOAD, k
    msg[0] += k
    qhead, cseq, gen, alive, pending = (R[RT_QHEAD], R[RT_CSEQ], R[RT_GEN], R[RT_ALIVE],
                                        R[RT_PENDING])
    bnd_base, counters = R[RT_BND_BASE], R[RT_COUNTERS]
    woken, wn = R[RT_WOKEN], R[RT_WOKEN_N]
    bnd_req = R[RT_BND_REQ]
    src = ob[_PAYC]
    rows = PA[0]
    order = route_order(ob, n)
    for j in range(n):
        i = order[j]
        kind = kinds[i]
        if kind == OB_CREATE:
            continue
        if kind == OB_RESPONSE:
            g = ob[_DST][i]
            if alive[g] == 0 or np.int64(gen[g]) != src[i, PAYLOAD_W - 1]:
                counters[0, _LATE] += 1
                continue
        else:
            g = bnd_base[ob[_BND][i]] + ob[_DST][i]
            if kind == OB_REQUEST:
                bnd_req[ob[_BND][i]] += 1
        row = pay_alloc(PA, 0)
        for c in range(PAYLOAD_W):
            rows[row, c] = src[i, c]
        sq = cseq[g]
        cseq[g] = sq + 1
        q_push(P, 0, qhead, g, ob[_TIME][i], ob[_PRIO][i], ob[_CAUSE][i], sq, ob[_RESP_KIND][i],
               ob[_TARGET][i], ob[_TAG][i], row)
        mark_touched(R, g)
        if kind == OB_RESPONSE:
            pending[g] -= 1
            if pending[g] == 0:
                _unlist_suspended(R, g)
                resume_owner(P, qhead, g)
                woken[wn[0]] = g
                wn[0] += 1
    return ROUTED, k

