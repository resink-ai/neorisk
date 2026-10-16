import numpy as np
import pytest

from neorisk_simkit.engine import calendar as cal
from neorisk_simkit.engine import cmdq


def _pool(cap=64, workers=2):
    pool = cmdq.NodePool(cap, workers)
    assert pool.refill(0, cap // 2) and pool.refill(1, cap // 2)
    return pool


def _drain(P, qhead, g, w=0):
    out = []
    while True:
        n = cmdq.q_pop(P, qhead, g)
        if n < 0:
            return out
        out.append((int(P[0][n]), int(P[1][n] >> 56), int(P[1][n] & ((1 << 56) - 1)),
                    int(P[2][n]), int(P[5][n])))
        cmdq.q_free(P, w, n)


def test_pop_order_is_time_priority_cause_seq():
    pool = _pool()
    P, qhead = pool.as_tuple(), np.full(4, -1, np.int32)
    items = [(10, 5, 1, 0, 1), (5, 5, 9, 1, 2), (10, 1, 7, 2, 3), (10, 5, 1, 3, 4),
             (10, 5, 0, 4, 5), (5, 0, 0, 5, 6)]
    for t, prio, cause, seq, kind in [items[i] for i in (3, 0, 5, 2, 1, 4)]:
        assert cmdq.q_push(P, 0, qhead, 2, t, prio, cause, seq, kind, 0, 0, -1) >= 0
    got = _drain(P, qhead, 2)
    assert [x[4] for x in got] == [6, 2, 3, 5, 1, 4]


def test_priority_inversion_same_time():
    pool = _pool()
    P, qhead = pool.as_tuple(), np.full(1, -1, np.int32)
    cmdq.q_push(P, 0, qhead, 0, 100, 5, 1, 0, 1, 0, 0, -1)      # debit, scheduled first
    cmdq.q_push(P, 0, qhead, 0, 100, 1, 3, 1, 2, 0, 0, -1)      # credit, scheduled later
    assert [x[4] for x in _drain(P, qhead, 0)] == [2, 1]


def test_worker_free_lists_and_refill():
    pool = cmdq.NodePool(4, 2)
    P, qhead = pool.as_tuple(), np.full(1, -1, np.int32)
    assert cmdq.q_push(P, 1, qhead, 0, 1, 5, 0, 0, 1, 0, 0, -1) == -1   # worker 1 has nothing
    assert pool.refill(1, 3) and not pool.refill(0, 2)                  # reserve holds 1 node
    for s in range(3):
        assert cmdq.q_push(P, 1, qhead, 0, 1, 5, 0, s, 1, 0, 0, -1) >= 0
    assert cmdq.q_push(P, 1, qhead, 0, 1, 5, 0, 9, 1, 0, 0, -1) == -1
    n = cmdq.q_pop(P, qhead, 0)
    cmdq.q_free(P, 0, n)                                                # freed into worker 0
    pool.splice_all()
    assert pool.in_use() == 2 and pool.reserve_n[0] == 2


def test_pack_key_ranges():
    assert cmdq.pack_key(5, 7) == (5 << 56) | 7
    with pytest.raises(ValueError, match="priority out of range"):
        cmdq.pack_key(64, 0)
    with pytest.raises(ValueError, match="cause_lamport out of range"):
        cmdq.pack_key(1, 1 << 56)


def test_payload_pool():
    pp = cmdq.PayloadPool(3, 1)
    assert pp.refill(0, 3)
    PA = pp.as_tuple()
    rows = [cmdq.pay_alloc(PA, 0) for _ in range(4)]
    assert sorted(rows[:3]) == [0, 1, 2] and rows[3] == -1
    cmdq.pay_free(PA, 0, rows[0])
    assert cmdq.pay_alloc(PA, 0) == rows[0]
    assert pp.rows.shape == (3, cmdq.PAYLOAD_W)


def test_calendar_collects_each_slot_once_and_skips_stale():
    c = cal.Calendar(n_slots=8, origin_us=0, width_us=100, n_buckets=16, capacity=64)
    C = c.as_tuple()
    next_t = np.full(8, np.iinfo(np.int64).max, np.int64)
    for g, t in [(1, 50), (2, 150), (3, 420), (4, 99)]:
        next_t[g] = t
        assert cal.cal_push(C, g, t)
    next_t[2] = 260                       # slot 2 moved later: its first entry is now stale
    cal.cal_push(C, 2, 260)
    out = np.zeros(8, np.int32)
    n = cal.cal_collect(C, next_t, 0, 200, out)
    assert sorted(out[:n].tolist()) == [1, 4]
    n = cal.cal_collect(C, next_t, 200, 400, out)
    assert out[:n].tolist() == [2]
    n = cal.cal_collect(C, next_t, 400, 500, out)
    assert out[:n].tolist() == [3]


def test_calendar_straddling_bucket_keeps_later_entries():
    c = cal.Calendar(n_slots=4, origin_us=0, width_us=100, n_buckets=4, capacity=16)
    C = c.as_tuple()
    next_t = np.array([10, 60, 0, 0], np.int64)
    cal.cal_push(C, 0, 10)
    cal.cal_push(C, 1, 60)
    out = np.zeros(4, np.int32)
    assert out[: cal.cal_collect(C, next_t, 0, 50, out)].tolist() == [0]
    assert out[: cal.cal_collect(C, next_t, 50, 100, out)].tolist() == [1]


def test_calendar_compaction_when_full():
    c = cal.Calendar(n_slots=4, origin_us=0, width_us=10, n_buckets=4, capacity=3)
    C = c.as_tuple()
    never = np.iinfo(np.int64).max
    next_t = np.array([5, 5, never, 5], np.int64)
    assert cal.cal_push(C, 0, 5) and cal.cal_push(C, 1, 5)
    next_t[0] = 7                          # slot 0 moved later: its first entry is now stale
    assert cal.cal_push(C, 0, 7)
    assert not cal.cal_push(C, 3, 5)       # 3 entries (one stale): the entry pool is full
    c.compact(next_t)                      # rebuild drops the stale entry
    C = c.as_tuple()
    assert cal.cal_push(C, 3, 5)           # compaction freed space
    out = np.zeros(4, np.int32)
    n = cal.cal_collect(C, next_t, 0, 10, out)
    assert sorted(out[:n].tolist()) == [0, 1, 3]


def test_caps_agree_with_payload_width():
    from neorisk_simkit.spec import caps
    assert caps.PAYLOAD_W == cmdq.PAYLOAD_W
    assert caps.OUTBOX_ROW_BYTES == 8 * 12 + 8 * cmdq.PAYLOAD_W
