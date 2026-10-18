import numpy as np
import pytest
from conftest import make_run
from conftest import records_of as _records

from neorisk_simkit.engine import AbiViolation, EngineError
from neorisk_simkit.engine.world import World

H = 3_600_000_000


def _world(name="mini", overrides=(), checked=False, force=None, threads=1):
    run = make_run(name, overrides, **({"force_capacity": force} if force else {}))
    return run, World.build(run, threads=threads, checked=checked)


def test_population_admission():
    run, w = _world()
    t0 = run.start_us - run.warmup_us
    slots = w.admit_population(t0, t0 + 1)
    assert len(slots) == 100                                  # initial = 0.5 of 200
    assert (w.hidden.alive[slots] == 1).all() and (w.hidden.qhead[slots] >= 0).all()
    later = w.admit_population(t0 + 1, run.start_us + run.span_us)
    assert len(later) == 100 and len(np.intersect1d(slots, later)) == 0


def test_owner_run_assigns_lamport_and_seq():
    run, w = _world(overrides=["behavior.take_p=0.0"])
    t0 = run.start_us - run.warmup_us
    slots = w.admit_population(t0, t0 + 1)
    w.run_slots(0, slots, t0 + 6 * H, owners=True)
    joined = _records(w, "user_joined")
    assert len(joined["time"]) == 100 and (joined["time"] == t0).all()
    assert (joined["lamport"] == 1).all() and (joined["seq"] == 0).all()
    ping = _records(w, "ping")
    for pid in np.unique(ping["pid"]):
        mine = ping["pid"] == pid
        assert (np.diff(ping["lamport"][mine]) > 0).all()
        assert ping["seq"][mine].tolist() == list(range(1, mine.sum() + 1))
    assert (ping["time"] < t0 + 6 * H).all()


def test_reject_advances_occurrence_and_retires():
    run, w = _world(overrides=["behavior.max_pings=1", "behavior.take_p=0.0"])
    t0 = run.start_us - run.warmup_us
    slots = w.admit_population(t0, t0 + 1)
    w.run_slots(0, slots, run.start_us + run.span_us, owners=True)
    assert w.stats["rejects"]["user_main"] == 100                       # one reject per user
    assert (w.hidden.occ[slots, 0] == 3).all()                # START, ping, rejected ping
    assert (w.hidden.retire_at[slots] < np.iinfo(np.int64).max).all()


def test_retry_with_tiny_slabs_gives_identical_records():
    over = ["behavior.take_p=0.0"]
    run, big = _world(overrides=over)
    _, small = _world(overrides=over, force={"records:ping": 1, "timers": 1})
    t0 = run.start_us - run.warmup_us
    for w in (big, small):
        w.run_slots(0, w.admit_population(t0, t0 + 1), t0 + 12 * H, owners=True)
    a, b = _records(big, "ping"), _records(small, "ping")
    assert all(np.array_equal(a[k], b[k]) for k in a)
    assert small.stats["retries"] > big.stats["retries"]


def test_request_suspends_owner():
    run, w = _world(overrides=["behavior.take_p=1.0"])
    t0 = run.start_us - run.warmup_us
    slots = w.admit_population(t0, t0 + 1)
    w.run_slots(0, slots, t0 + 24 * H, owners=True)
    assert (w.hidden.pending[slots] == 1).all()               # every user waits for one answer
    ob = w.slabs[0].outbox_view()
    assert len(ob["kind"]) == 100 and (ob["kind"] == 1).all()


def test_full_outbox_is_moved_aside_instead_of_livelocking():
    run, w = _world(overrides=["behavior.take_p=1.0"], force={"requests": 1})
    t0 = run.start_us - run.warmup_us
    slots = w.admit_population(t0, t0 + 1)
    w.run_slots(0, slots, t0 + 24 * H, owners=True)
    assert (w.hidden.pending[slots] == 1).all()
    moved = sum(len(ob["kind"]) for ob in w.pending_outbox[0])
    assert moved + len(w.slabs[0].outbox_view()["kind"]) == 100


@pytest.mark.parametrize("mode,exc,msg", [
    (0, AbiViolation, "wrote before returning reject"),
    (1, AbiViolation, "emit beyond reservation: e"),
    (2, EngineError, "timer scheduled before current time"),
    (3, AbiViolation, "wrote before returning RETRY"),
])
@pytest.mark.checked
def test_checked_mode_catches_abi_violations(mode, exc, msg):
    run, w = _world("bad_abi", overrides=[f"mode={mode}"], checked=True)
    slots = w.admit_population(run.start_us, run.start_us + 1)
    with pytest.raises(exc, match=msg):
        w.run_slots(0, slots, run.start_us + H, owners=True)


def test_unchecked_mode_still_rejects_time_travel():
    run, w = _world("bad_abi", overrides=["mode=2"])
    slots = w.admit_population(run.start_us, run.start_us + 1)
    with pytest.raises(EngineError, match="timer scheduled before current time"):
        w.run_slots(0, slots, run.start_us + H, owners=True)


@pytest.mark.checked
def test_checked_calendar_rejects_lost_pushes_and_window_gaps():
    """Contract from Task 7: contiguous collect windows, no push below the collected horizon."""
    from neorisk_simkit.engine import calendar as cal
    run, w = _world(checked=True)
    t0 = run.start_us - run.warmup_us
    assert w.calendar.params[2] * w.calendar.params[1] >= run.warmup_us + run.span_us
    C, out = w.calendar.as_tuple(), np.zeros(w.G, np.int32)
    next_t = np.full(w.G, np.iinfo(np.int64).max, np.int64)
    next_t[5] = t0 + 10
    assert cal.cal_push(C, 5, t0 + 10)
    assert out[: cal.cal_collect(C, next_t, t0, t0 + H, out)].tolist() == [5]
    with pytest.raises(EngineError, match="below the collected horizon"):
        cal.cal_push(C, 6, t0 + H - 1)
    with pytest.raises(EngineError, match="must be contiguous"):
        cal.cal_collect(C, next_t, t0 + 2 * H, t0 + 3 * H, out)


# ---------------------------------------------------------------- fix round 1 regressions
def test_concurrent_refills_keep_the_node_reserve_consistent():
    import threading
    _, w = _world(threads=4)
    pool, start = w.pool, threading.Barrier(4)

    def hammer(worker):
        start.wait()
        for _ in range(60):
            w._refill_nodes(worker)

    ts = [threading.Thread(target=hammer, args=(k,)) for k in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert int(pool.reserve_n[0] + pool.free_n.sum()) == pool.capacity

    def walk(head):
        out, n = [], head
        while n >= 0:
            out.append(n)
            n = pool.next[n]
        return out

    nodes = walk(pool.reserve_head[0]) + [x for k in range(4) for x in walk(pool.free_head[k])]
    assert len(nodes) == len(set(nodes)) == pool.capacity
    assert [len(walk(pool.free_head[k])) for k in range(4)] == pool.free_n.tolist()


def test_forced_timer_capacity_bounds_the_worker_free_list(monkeypatch):
    """Rejects free nodes without queueing new ones; the forced list must not keep them."""
    run, w = _world(overrides=["behavior.take_p=0.0", "behavior.max_pings=1"],
                    force={"timers": 1})
    t0 = run.start_us - run.warmup_us
    real, seen, statuses = w.eng.run_partitions, [], []

    def spy(W, out, worker, slots, start, limit_t, owners):
        seen.append(int(w.pool.free_n[worker]))           # what the kernels will reserve from
        status, i = real(W, out, worker, slots, start, limit_t, owners)
        statuses.append(status)
        return status, i

    monkeypatch.setattr(w.eng, "run_partitions", spy)
    w.run_slots(0, w.admit_population(t0, t0 + 1), run.start_us + run.span_us, owners=True)
    assert w.stats["rejects"]["user_main"] == 100
    assert max(seen) <= 1 and int(w.pool.free_n[0]) <= 1
    assert int(w.pool.reserve_n[0] + w.pool.free_n.sum()) == w.pool.capacity   # all idle
    assert statuses.count(2) >= 100                           # the list is rebalanced each time


def _periodic(force=None):
    run, w = _world("periodic", force=force)
    w.init_shards()
    shards = np.arange(w.slot_base["clock"], w.slot_base["clock"] + 3)
    w.run_slots(0, shards, run.start_us + run.span_us, owners=False)
    return run, w, _records(w, "ticked")


def test_periodic_shard_processes_are_phase_spread_jittered_and_retry_safe():
    run, w, r = _periodic()
    _, _, r2 = _periodic()
    _, small, r3 = _periodic(force={"records:ticked": 1})
    assert all(np.array_equal(r[k], r2[k]) and np.array_equal(r[k], r3[k]) for k in r)
    assert small.stats["retries"] > 0                         # retried STARTs queued once
    every = 2 * H
    phases = []
    for c in range(3):
        mine = r["clock"] == c
        assert r["j"][mine].tolist() == list(range(6)) == (r["n"][mine] - 1).tolist()
        t = r["time"][mine] - run.start_us
        phases.append(int(t[0]))
        assert 0 <= t[0] < every
        late = t[1:] - t[0] - every * np.arange(1, 6)          # jitter of occurrences 1..5
        assert (late >= 0).all() and (late > 0).any() and (late < 600_000_000).all()
    assert len(set(phases)) == 3
    assert (w.hidden.occ[w.slot_base["clock"]:w.slot_base["clock"] + 3, 0] == 6).all()
    assert (small.hidden.cseq == w.hidden.cseq).all()


def test_unchecked_retry_cap_stops_a_kernel_that_never_progresses():
    run, w = _world("bad_abi", overrides=["mode=3"])
    slots = w.admit_population(run.start_us, run.start_us + 1)
    with pytest.raises(EngineError, match="command retried 8 times without progress"):
        w.run_slots(0, slots, run.start_us + H, owners=True)


def test_clean_run_end_only_trims_a_forced_node_list():
    """After DONE a forced list below its size is not topped up: an empty reserve is fine."""
    run, w = _world(force={"timers": 4}, threads=2)
    t0 = run.start_us - run.warmup_us
    slots = w.admit_population(t0, t0 + 1)
    w.pool.refill(1, int(w.pool.reserve_n[0]))       # reserve empty; worker 0 holds 0 < 4
    w.run_slots(0, slots, t0, owners=True)            # nothing runs before t0: DONE at once
    assert int(w.pool.free_n[0]) == 0 and int(w.pool.reserve_n[0]) == 0


def test_a_partition_never_runs_a_command_before_its_last_one():
    """Always-on guard: a command dated before the partition's last executed command fails."""
    from neorisk_simkit.engine.abi import PRIO_MESSAGE
    from neorisk_simkit.engine.cmdq import q_push
    run, w = _world("ordering")
    t0 = run.start_us - run.warmup_us
    w.run_slots(0, w.admit_population(t0, t0 + 1), t0 + H, owners=True)
    w.route()
    g = w.slot_base["ledger"]
    w.run_slots(0, np.array([g]), t0 + H, owners=False)       # the shard ran at t0
    ledger = w.plan.process("ledger_desk")
    w._take_reserve_nodes(1)
    q_push(w._reserve_pool(), 0, w.hidden.qhead, g, t0 - 1, PRIO_MESSAGE, 0, 99, 1,
           ledger.action_id, 0, -1)
    with pytest.raises(EngineError, match="shard ledger: ledger_desk .*request note.* before"):
        w.run_slots(0, np.array([g]), t0 + H, owners=False)
