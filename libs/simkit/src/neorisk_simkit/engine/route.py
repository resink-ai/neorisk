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
  bnd_resp  int64[boundaries]: responses routed per boundary code over the run (D40)
  shard_req int64[max(1, G - shard_lo)]: requests delivered per shard slot over the run
  shard_lo  int64[1]: the first shard slot
  hid       (ptype, pid, ckey): views of the hidden arrays the sender keys read (D61)
  created   uint8[G]: the hidden `created` flag, 1 for a created owner's slot (D61); per slot,
            since one `child_of` owner type can hold both population and created owners
  adm       int64[2]: created owners admitted this step, `budget.max_admissions_per_step`
            (D44; queued creations count against the limit as they are routed)
"""

from __future__ import annotations

import numpy as np
from numba import njit

from neorisk_simkit.engine.admit import CQ_N, cq_push
from neorisk_simkit.engine.cmdq import P_FREE_N, PAY_KIND, PAYLOAD_W, pay_alloc, q_push_from
from neorisk_simkit.engine.codegen import COUNTERS
from neorisk_simkit.engine.slabs import OB_CREATE, OB_REQUEST, OB_RESPONSE, OUTBOX_COLS

(RT_QHEAD, RT_CSEQ, RT_GEN, RT_ALIVE, RT_PENDING, RT_SUSP_T, RT_SUSP_DELTA, RT_POOL, RT_PAY,
 RT_BND_BASE, RT_COUNTERS, RT_MSG, RT_WOKEN, RT_WOKEN_N, RT_TMASK, RT_TLIST, RT_TN, RT_SUSP,
 RT_SUSP_N, RT_SMASK, RT_BND_REQ, RT_SPOS, RT_BND_RESP, RT_SHARD_REQ, RT_SHARD_LO, RT_HID,
 RT_CREATED, RT_ADM) = range(28)

# route_outbox statuses
ROUTED, NEED_MESSAGES, NEED_NODES, NEED_PAYLOAD, NEED_CREATES = 0, 1, 2, 3, 4

_OB = {c: i for i, c in enumerate(OUTBOX_COLS)}
_KIND, _BND, _TIME, _PRIO, _CAUSE = (_OB["kind"], _OB["bnd"], _OB["time"], _OB["prio"],
                                     _OB["cause"])
_SRC_G, _SRC_SEQ, _DST, _TAG = _OB["src_g"], _OB["src_seq"], _OB["dst"], _OB["tag"]
_RESP_KIND, _TARGET, _OB_SRC_PID = _OB["resp_kind"], _OB["target_action"], _OB["src_pid"]
_PAYC = len(OUTBOX_COLS)
_LATE = COUNTERS.index("late_messages")
_CMDS = COUNTERS.index("commands")
_I64_MAX = np.iinfo(np.int64).max


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
    """The safe horizon H = min(step end, min over suspended owners of (request time + delta),
    earliest unadmitted creation `create_min`) (D5); the suspended term is the heap's top."""
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
def resume_owner(P, pay_rows, qhead, g):
    """Blocking suspension: the owner resumes at T_r, the latest time among its delivered
    responses, and runs nothing dated before it. Its queue becomes: the responses, then the
    other commands dated before T_r, then those dated exactly T_r (each group in its (time,
    key, sender key, seq) order), all re-dated to T_r — the effective time max(time, T_r) —
    then the rest. The queue stays sorted by time.

    A node is a response iff its payload row carries the delivered kind `OB_RESPONSE` in
    column `PAY_KIND` (D39); timers, continuations and delivered messages are not.

    Commands pushed at T_r while that re-dated prefix is still queued (a `continue_at`, or a
    timer at `ctx.t` from the response handler): `q_push` walks the queue and inserts before
    the first node with the same time and a greater `(key, sender key, seq)`. The prefix is
    not sorted by key (it keeps the group order above), so the new command lands before the
    first remaining prefix node with a greater key: a `PRIO_CONTINUE` continuation runs before
    every deferred command still queued, a timer at priority p before the first deferred
    command of priority > p (or of equal priority and a later cause). This depends only on the
    queue's contents, never on step boundaries, workers or slabs, so it is invariant; it
    equals the canonical `(time, key, sender key, seq)` order whenever the remaining prefix
    happens to be sorted by key.
    """
    ptime, nxt, ppay = P[0], P[4], P[7]
    t_r = np.int64(-(2 ** 63))
    node = qhead[g]
    while node >= 0:
        if ppay[node] >= 0 and pay_rows[ppay[node], PAY_KIND] == OB_RESPONSE:
            t_r = max(t_r, ptime[node])
        node = nxt[node]
    heads = np.full(3, -1, np.int32)      # 0 responses, 1 earlier commands, 2 commands at t_r
    tails = np.full(3, -1, np.int32)
    node = qhead[g]
    while node >= 0 and ptime[node] <= t_r:
        nx = nxt[node]
        nxt[node] = -1
        if ppay[node] >= 0 and pay_rows[ppay[node], PAY_KIND] == OB_RESPONSE:
            k = 0
        else:
            k = 1 if ptime[node] < t_r else 2
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
def sender_keys(R, src_g, n):
    """The step-invariant sender key of each of the first n rows, from the sender's slot (D61).

    A population owner or a shard keys as `(ptype, 0, pid, 0, 0, 0)`; its `pid` never
    changes. A created owner (hidden `created` flag, per slot) keys as `(ptype, 1, created_at, creator
    commit lamport, creator inst, k)` from `ckey`, written at its admission: its `pid` is a
    provisional handle in its creation step and a per-step dense index afterwards, so it
    would order the owner differently under different step lengths."""
    ptype, pid, ckey = R[RT_HID]
    created = R[RT_CREATED]
    k0, k1, k2 = np.zeros(n, np.int64), np.zeros(n, np.int64), np.zeros(n, np.int64)
    k3, k4, k5 = np.zeros(n, np.int64), np.zeros(n, np.int64), np.zeros(n, np.int64)
    for i in range(n):
        g = src_g[i]
        k0[i] = ptype[g]
        if created[g]:
            k1[i] = 1
            k2[i], k3[i], k4[i], k5[i] = ckey[g, 0], ckey[g, 1], ckey[g, 2], ckey[g, 3]
        else:
            k2[i] = pid[g]
    return k0, k1, k2, k3, k4, k5


@njit(cache=True, nogil=True)
def _then_by(order, key):
    """`order` stably re-sorted by `key` (the next more significant key)."""
    return order[np.argsort(key[order], kind="mergesort")]


@njit(cache=True, nogil=True)
def route_order(ob, n, R):
    """Row order by (time, prio, cause, sender key, src_seq) (D61): stable sorts, last key
    first. The sender's slot is still alive when its outbox is routed (routing runs in the
    phase that committed the rows), so `sender_keys` describe the sender."""
    return _route_order(ob, n, sender_keys(R, ob[_SRC_G][:n], n))


@njit(cache=True, nogil=True)
def _route_order(ob, n, keys):
    k0, k1, k2, k3, k4, k5 = keys
    order = np.argsort(ob[_SRC_SEQ][:n], kind="mergesort")
    if k1.any():                          # k3..k5 are zero unless a created owner sent a row
        order = _then_by(order, k5)
        order = _then_by(order, k4)
        order = _then_by(order, k3)
    order = _then_by(order, k2)
    if k1.any():
        order = _then_by(order, k1)
    order = _then_by(order, k0)
    order = _then_by(order, ob[_CAUSE][:n])
    order = _then_by(order, ob[_PRIO][:n])
    return _then_by(order, ob[_TIME][:n])


@njit(cache=True, nogil=True)
def _commit_ordinal(ob, n, i):
    """`k` of creation row i: its handle's per-step ordinal minus the smallest one among the
    creation rows of its namespace in the same commit (contracts C1). A commit's outbox rows
    are contiguous (the kernel reserved them all before writing any), so the commit is the
    maximal run of rows around i from the same sender slot with the same cause lamport."""
    kinds, bnd, cause, dst, src = ob[_KIND], ob[_BND], ob[_CAUSE], ob[_DST], ob[_PAYC]
    sg, ca = src[i, 7], cause[i]
    lo = i
    while lo > 0 and src[lo - 1, 7] == sg and cause[lo - 1] == ca:
        lo -= 1
    hi = i
    while hi + 1 < n and src[hi + 1, 7] == sg and cause[hi + 1] == ca:
        hi += 1
    o = dst[i] & 0xFFFFFF
    m = o
    for j in range(lo, hi + 1):
        if kinds[j] == OB_CREATE and bnd[j] == bnd[i]:
            m = min(m, dst[j] & 0xFFFFFF)
    return o - m


@njit(cache=True, nogil=True)
def route_outbox(R, CQ, ob, n):
    """Deliver the first n rows of outbox `ob` (`OUTBOX_COLS` then `pay`); (status, value).

    Requests go to the shard queue at the request time, messages to the shard queue at their
    delivery time, responses to the requesting owner if its slot generation still matches
    (then `pending -= 1`; otherwise `late_messages += 1`). Every delivered command gets a
    payload row copied from the outbox, with the delivered kind written into its `PAY_KIND`
    column once a response's generation check has read it (D39). The receiver queues it under
    the sender's key and `src_seq` (D61), so its tie order does not depend on the routing
    round. Responses routed and requests delivered are counted per boundary
    (`RT_BND_RESP`, `RT_BND_REQ`) and per shard slot (`RT_SHARD_REQ`). `OB_CREATE` rows join
    the pending-creation queue `CQ` with their `k` (D44, F-10).

    Nothing is delivered or queued unless every row fits: the step's message budget
    (`NEED_MESSAGES`, value = messages needed), the admission limit (`NEED_CREATES`, value =
    the outbox row of the first creation in routing order beyond `R[RT_ADM]`'s limit, counting
    the creations admitted and queued already), and both reserves (`NEED_NODES`,
    `NEED_PAYLOAD`, value = rows needed).
    """
    kinds = ob[_KIND]
    k = np.int64(0)
    nc = np.int64(0)
    for i in range(n):
        if kinds[i] == OB_CREATE:
            nc += 1
        else:
            k += 1
    msg = R[RT_MSG]
    if msg[0] + k > msg[1]:
        return NEED_MESSAGES, msg[0] + k
    keys = sender_keys(R, ob[_SRC_G][:n], n)
    k0, k1, k2, k3, k4, k5 = keys
    order = _route_order(ob, n, keys)
    src = ob[_PAYC]
    if nc > 0:
        adm = R[RT_ADM]
        have = adm[0] + CQ[CQ_N][0]
        for j in range(n):
            i = order[j]
            if kinds[i] == OB_CREATE:
                have += 1
                if have > adm[1]:
                    return NEED_CREATES, np.int64(i)
    P, PA = R[RT_POOL], R[RT_PAY]
    if P[P_FREE_N][0] < k:
        return NEED_NODES, k
    if PA[3][0] < k:
        return NEED_PAYLOAD, k
    if nc > 0:
        for i in range(n):
            if kinds[i] == OB_CREATE:
                cq_push(CQ, ob[_TIME][i], ob[_PRIO][i], ob[_CAUSE][i], ob[_OB_SRC_PID][i],
                        ob[_SRC_SEQ][i], ob[_BND][i], ob[_DST][i], src[i, 7], src[i, 10],
                        _commit_ordinal(ob, n, i), src, i)
    msg[0] += k
    qhead, gen, alive, pending = R[RT_QHEAD], R[RT_GEN], R[RT_ALIVE], R[RT_PENDING]
    bnd_base, counters = R[RT_BND_BASE], R[RT_COUNTERS]
    woken, wn = R[RT_WOKEN], R[RT_WOKEN_N]
    bnd_req, bnd_resp, shard_req = R[RT_BND_REQ], R[RT_BND_RESP], R[RT_SHARD_REQ]
    shard_lo = R[RT_SHARD_LO][0]
    rows = PA[0]
    for j in range(n):
        i = order[j]
        kind = kinds[i]
        if kind == OB_CREATE:
            continue
        if kind == OB_RESPONSE:
            g = ob[_DST][i]
            if alive[g] == 0 or np.int64(gen[g]) != src[i, PAY_KIND]:
                counters[0, _LATE] += 1
                continue
        else:
            g = bnd_base[ob[_BND][i]] + ob[_DST][i]
            if kind == OB_REQUEST:
                bnd_req[ob[_BND][i]] += 1
                shard_req[g - shard_lo] += 1
        row = pay_alloc(PA, 0)
        for c in range(PAYLOAD_W):
            rows[row, c] = src[i, c]
        rows[row, PAY_KIND] = kind             # the delivered kind (D39)
        if kind == OB_RESPONSE:
            bnd_resp[ob[_BND][i]] += 1
        # the receiver orders tied commands by the sender's key and seq, never by arrival, so
        # the round a command arrives in (which depends on step length) cannot reorder it (D61)
        q_push_from(P, 0, qhead, g, ob[_TIME][i], ob[_PRIO][i], ob[_CAUSE][i], ob[_SRC_SEQ][i],
                    ob[_RESP_KIND][i], ob[_TARGET][i], ob[_TAG][i], row, 2 * k0[i] + k1[i],
                    k2[i], k3[i], k4[i], k5[i])
        mark_touched(R, g)
        if kind == OB_RESPONSE:
            pending[g] -= 1
            if pending[g] == 0:
                _unlist_suspended(R, g)
                resume_owner(P, rows, qhead, g)
                woken[wn[0]] = g
                wn[0] += 1
    return ROUTED, k

