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
