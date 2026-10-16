import numpy as np
import pytest
from conftest import make_run, records_of

from neorisk_simkit.engine import CapExceeded
from neorisk_simkit.engine.rounds import run_step
from neorisk_simkit.engine.route import safe_horizon
from neorisk_simkit.engine.world import World

H = 3_600_000_000


def _step(name, overrides=(), threads=1, engine=None):
    run = make_run(name, overrides, **(engine or {}))
    w = World.build(run, threads=threads)
    w.init_shards()
    t0 = run.start_us - run.warmup_us
    stats = run_step(w, t0, t0 + run.engine.step_us)
    return run, w, stats


def _rows(w, table):
    return records_of(w, table)


def test_safe_horizon():
    inf = np.iinfo(np.int64).max
    assert safe_horizon(1000, np.array([], np.int64), np.array([], np.int64),
                        np.array([], np.int64)) == 1000
    assert safe_horizon(1000, np.array([100, 50], np.int64), np.array([200, 300], np.int64),
                        np.array([], np.int64)) == 300
    assert safe_horizon(1000, np.array([100], np.int64), np.array([200], np.int64),
                        np.array([120], np.int64)) == 120
    assert safe_horizon(250, np.array([100], np.int64), np.array([200], np.int64),
                        np.array([inf], np.int64)) == 250


def test_mini_step_closes_with_responses_after_delta():
    run, w, stats = _step("mini", ["behavior.take_p=1.0"])
    t1 = run.start_us - run.warmup_us + run.engine.step_us
    taken = np.concatenate([_rows(w, "item_taken")["time"], _rows(w, "take_failed")["time"]])
    expected = sorted(int(x) + 200_000 for x in taken if x + 200_000 < t1)
    took = _rows(w, "took")
    assert len(expected) > 0 and expected == sorted(took["time"].tolist())
    assert w.next_command_time(owners=False) >= t1
    assert stats.rounds >= 2


def test_priority_inversion_credit_runs_before_debit():
    _, w, _ = _step("ordering")
    cr, de = _rows(w, "credited"), _rows(w, "debited")
    assert len(cr["time"]) == 2 and len(de["time"]) == 2
    assert (cr["time"] == de["time"]).all()
    assert (cr["lamport"] < de["lamport"]).all()
    assert de["balance_after"].tolist() == [0, 0]
    assert w.stats["rejects"].get("acct_main", 0) == 0


@pytest.mark.parametrize("threads", [1, 4])
def test_equal_keys_order_by_partition_id(threads):
    _, w, _ = _step("ordering", threads=threads)
    opened = _rows(w, "opened")
    assert (opened["lamport"] == 1).all() and opened["pid"].tolist() == sorted(opened["pid"])
    noted = _rows(w, "noted")
    assert noted["v"].tolist() == [0, 1]                 # shard handled acct 0 first
    assert noted["lamport"].tolist() == [2, 3]


def test_threads_do_not_change_mini_records():
    a = _step("mini", ["behavior.take_p=0.5"], threads=1)[1]
    b = _step("mini", ["behavior.take_p=0.5"], threads=4,
              engine={"parallel_min_partitions": 1})[1]
    for table in ("ping", "took", "item_taken"):
        ra, rb = _rows(a, table), _rows(b, table)
        assert all(np.array_equal(ra[k], rb[k]) for k in ra)


def test_late_response_to_retired_slot_is_dropped():
    _, w, _ = _step("mini", ["behavior.take_p=1.0"])
    assert w.route_stale_response_for_test() == 1          # bumps gen of a waiting slot, routes
    assert w.stats["late_messages"] == 1


def test_message_cap():
    with pytest.raises(CapExceeded, match="requests_and_inboxes"):
        _step("mini", ["behavior.take_p=1.0"],
              engine={"max_messages_per_step": 1})


# ---------------------------------------------------------------- beyond the brief
def _steps(overrides=(), n=3, **engine):
    run = make_run("mini", overrides, **engine)
    w = World.build(run, threads=1)
    t, stats = run.start_us - run.warmup_us, []
    for _ in range(n):
        stats.append(run_step(w, t, t + run.engine.step_us))
        t += run.engine.step_us
    return w, stats


def test_compiled_rounds_match_python_rounds_over_steps():
    over = ["behavior.take_p=0.5"]
    a, sa = _steps(over, parallel_min_partitions=10**9)     # every round after the first compiled
    b, sb = _steps(over, parallel_min_partitions=1)         # no compiled round
    c, sc = _steps(over, parallel_min_partitions=64,        # compiled rounds stop for Python
                   force_capacity={"requests": 2, "records:ping": 1, "timers": 2})
    assert all(s.compiled_rounds > s.rounds // 2 for s in sa)
    assert all(s.compiled_rounds == 0 for s in sb)
    assert any(0 < s.compiled_rounds < s.rounds - 1 for s in sc)
    for x, y in ((sa, sb), (sa, sc)):
        assert [(s.rounds, s.owners_run, s.shard_cmds) for s in x] == \
            [(s.rounds, s.owners_run, s.shard_cmds) for s in y]
    for table in ("user_joined", "ping", "took", "item_taken", "take_failed"):
        ra, rb, rc = _rows(a, table), _rows(b, table), _rows(c, table)
        assert all(np.array_equal(ra[k], rb[k]) and np.array_equal(ra[k], rc[k]) for k in ra)


def test_suspended_owners_are_listed_once(monkeypatch):
    """An owner that suspends again after a resume must not get a second list entry (the list
    has one slot per partition)."""
    from neorisk_simkit.engine import route as rt
    run = make_run("mini", ["behavior.take_p=0.5"], parallel_min_partitions=1)
    w = World.build(run, threads=1)
    real, sizes = w.note_suspended, []

    def check(slots):
        real(slots)
        n = int(w.R[rt.RT_SUSP_N][0])
        listed = w.R[rt.RT_SUSP][:n]
        assert len(set(listed.tolist())) == n
        assert (w.R[rt.RT_SMASK].astype(bool) == np.isin(np.arange(w.G), listed)).all()
        sizes.append(n)

    monkeypatch.setattr(w, "note_suspended", check)
    t0 = run.start_us - run.warmup_us
    run_step(w, t0, t0 + run.engine.step_us)
    assert len(sizes) > 100 and max(sizes) > 0


def test_created_owners_start_at_creation_time_in_the_next_round():
    run, w, stats = _step("spawn")
    t0 = run.start_us - run.warmup_us
    spawned, paid = _rows(w, "spawned"), _rows(w, "paid")
    assert (paid["time"] == t0).all() and (spawned["time"] == t0).all()
    assert sorted(paid["pay_id"].tolist()) == sorted(spawned["pay_id"].tolist())
    assert (paid["pid"] == paid["pay_id"]).all() and (paid["lamport"] == 2).all()
    assert paid["amt"].tolist() == [100 + a for a in paid["acct_id"].tolist()]
    # D5: the creation bounds H at t0, so no shard runs before the payments start (round 2)
    assert stats.owners_run == [3, 3, 3] and stats.shard_cmds == [0, 6, 0]
    assert len(w.touched) == 3 + 3 + 2 and w.pending_creates == []


def test_messages_reach_shards_at_their_delivery_time():
    run, w, _ = _step("spawn")
    t0 = run.start_us - run.warmup_us
    ticked = _rows(w, "ticked")
    assert (ticked["time"] == t0 + 50_000).all() and sorted(ticked["v"].tolist()) == [0, 1, 2]
    assert (_rows(w, "answered")["time"] == t0 + 200_000).all()


def test_admission_cap_names_the_creating_process():
    with pytest.raises(CapExceeded, match=r"max_admissions_per_step .*in process acct_main$"):
        _step("spawn", ["budget.max_admissions_per_step=2"])


def test_request_to_a_missing_shard_names_the_process():
    from neorisk_simkit.engine import EngineError
    with pytest.raises(EngineError, match="acct_main: request ask to shard 5 but desk has 2"):
        _step("spawn", ["bad_shard=1"])


# ---------------------------------------------------------------- fix round 1 regressions
MS = 1_000


def test_suspension_blocks_until_the_response_arrives():
    """Reviewer repro: acct 0 asks at t and queues a second ask at t+10ms; acct 1 asks at
    t+50ms. Suspension is blocking, so acct 0's t+10ms timer runs at its response time t+100ms
    (after the response handler) and the shard sees the asks in time order."""
    run, w, _ = _step("blocking")
    t0 = run.start_us - run.warmup_us
    noted = _rows(w, "noted")
    assert (noted["time"] - t0).tolist() == [0, 50 * MS, 100 * MS]
    assert noted["v"].tolist() == [0, 1, 0]
    assert (np.diff(noted["lamport"]) > 0).all()
    later, acked = _rows(w, "later"), _rows(w, "acked")
    mine = later["acct_id"] == 0
    assert (later["time"][mine] - t0).tolist() == [100 * MS]          # effective time t + delta
    first_ack = acked["lamport"][(acked["acct_id"] == 0) & (acked["time"] == t0 + 100 * MS)]
    assert len(first_ack) == 1 and first_ack[0] < later["lamport"][mine][0]   # response first
    assert (acked["time"] - t0).tolist() == [100 * MS, 150 * MS, 200 * MS]


def test_requests_must_be_dated_ctx_t():
    from neorisk_simkit.engine import EngineError
    with pytest.raises(EngineError, match="acct_main: request ask must be dated ctx.t"):
        _step("spawn", ["request_delay=1"])


def test_route_order_sorts_equal_keys_by_partition_id_then_seq():
    from neorisk_simkit.engine.route import route_order
    from neorisk_simkit.engine.slabs import OUTBOX_COLS
    rng_ = np.random.default_rng(3)
    n = 40
    cols = {c: np.zeros(n, np.int64) for c in OUTBOX_COLS}
    cols["time"][:] = rng_.integers(0, 2, n)          # many rows tie on (time, prio, cause)
    cols["prio"][:] = 1
    cols["cause"][:] = rng_.integers(0, 2, n)
    cols["src_pid"][:] = rng_.permutation(n) // 4     # four rows per partition...
    cols["src_seq"][:] = rng_.permutation(n)          # ...told apart by seq
    ob = (*cols.values(), np.zeros((n, 12), np.int64))
    want = np.lexsort((cols["src_seq"], cols["src_pid"], cols["cause"], cols["prio"],
                       cols["time"]))
    assert route_order(ob, n).tolist() == want.tolist()


def test_creations_inside_compiled_rounds_return_to_python(monkeypatch):
    from neorisk_simkit.engine.codegen import DR_PYTHON, PH_ROUTE1, RS_PHASE
    run = make_run("spawn", ["create_on_answer=1"], parallel_min_partitions=10**9)
    w = World.build(run, threads=1)
    real, seen = w.eng.drain_small_rounds, []

    def spy(*args):
        code, n = real(*args)
        seen.append((int(code), int(w.round_state[RS_PHASE])))
        return code, n

    monkeypatch.setattr(w.eng, "drain_small_rounds", spy)
    t0 = run.start_us - run.warmup_us
    stats = run_step(w, t0, t0 + run.engine.step_us)
    assert (DR_PYTHON, PH_ROUTE1) in seen
    paid, answered = _rows(w, "paid"), _rows(w, "answered")
    assert len(paid["time"]) == 3 and (paid["time"] == t0 + 200 * MS).all()
    assert sorted(answered["time"].tolist()) == sorted(paid["time"].tolist())
    assert stats.owners_run[-1] == 3 and w.pending_creates == []


def test_safe_horizon_saturates():
    inf = np.iinfo(np.int64).max
    assert safe_horizon(1000, np.array([inf], np.int64), np.array([inf], np.int64),
                        np.array([], np.int64)) == 1000
