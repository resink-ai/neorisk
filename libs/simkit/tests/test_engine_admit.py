"""D44: created owners are admitted by generated compiled code, inside compiled rounds,
with exactly the records the Python admission produced."""

import numpy as np
import pytest
from conftest import make_run, records_of

from neorisk_simkit.engine import CapExceeded, rng
from neorisk_simkit.engine.admit import ADM_NODES, FreeSlots
from neorisk_simkit.engine.codegen import DR_PYTHON, PH_ADMIT, RS_PHASE, RS_STATUS
from neorisk_simkit.engine.rounds import run_step
from neorisk_simkit.engine.route import RT_ADM
from neorisk_simkit.engine.world import World

H = 3_600_000_000


def _steps(name, overrides=(), n=1, **engine):
    run = make_run(name, overrides, **engine)
    w = World.build(run, threads=1)
    w.init_shards()
    t, stats = run.start_us - run.warmup_us, []
    for _ in range(n):
        stats.append(run_step(w, t, t + run.engine.step_us))
        t += run.engine.step_us
    return run, w, stats


def test_mix4_matches_python_mix():
    for parts in [(1, 2, 3, 4), (-5, 2**62, 0, 7), (np.iinfo(np.int64).min, -1, 3, 0)]:
        assert int(rng.mix4(*parts)) == rng.mix(*parts)


def test_free_slots_are_fifo_with_sorted_returns():
    fs = FreeSlots([5, 3], [0, 5])
    assert fs.take(0, 2).tolist() == [0, 1] and fs.n(0) == 3
    fs.give(0, np.array([1, 0], np.int32))
    assert fs.take(0, 5).tolist() == [2, 3, 4, 0, 1]
    with pytest.raises(IndexError):
        fs.take(1, 4)


def test_creations_are_admitted_inside_compiled_rounds(monkeypatch):
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
    assert all(code != DR_PYTHON for code, _ in seen)
    assert stats.compiled_rounds == stats.rounds - 1          # all but the first round
    paid = records_of(w, "paid")
    assert len(paid["time"]) == 3 and (paid["time"] == t0 + 200_000).all()
    assert w.pending_creations() == 0


@pytest.mark.parametrize("name,overrides", [
    ("spawn", ["create_on_answer=1"]), ("spawn", []), ("chain", []), ("creators", []),
    ("trace_shopper", [])])
def test_compiled_and_python_admission_give_identical_records(name, overrides):
    n = 4 if name == "creators" else 1
    _, a, sa = _steps(name, overrides, n=n, parallel_min_partitions=10**9)
    _, b, sb = _steps(name, overrides, n=n, parallel_min_partitions=1)
    assert [(s.rounds, s.owners_run, s.shard_cmds) for s in sa] == \
        [(s.rounds, s.owners_run, s.shard_cmds) for s in sb]
    tables = [e.name for e in a.plan.events]
    for t in tables:
        ra, rb = records_of(a, t), records_of(b, t)
        assert all(np.array_equal(ra[k], rb[k]) for k in ra), t


def test_live_cap_names_the_creating_process():
    with pytest.raises(CapExceeded, match=r"live_partition_state .*in process a_main$"):
        _steps("chain", ["live=2"])


def test_admission_cap_still_names_the_creating_process():
    with pytest.raises(CapExceeded, match=r"max_admissions_per_step .*in process acct_main$"):
        _steps("spawn", ["budget.max_admissions_per_step=2"])


def test_admission_short_of_nodes_admits_nothing_and_retries_identically(monkeypatch):
    """F-10: `ADM_NODES` admits no row and leaves `CQ` (and each row's `k`) as it was; after the
    refill the records equal an unforced run's. The reserve is drained to one node before every
    compiled drain call (its free nodes go to worker 0's list), so admitting 4 b's and 4 c's
    (one START each) always finds the reserve short first."""
    _, base, _ = _steps("chain", parallel_min_partitions=10**9)
    run = make_run("chain", parallel_min_partitions=10**9)
    w = World.build(run, threads=1)
    w.init_shards()
    real, seen = w.eng.drain_small_rounds, []

    def starved(*args):
        spare = int(w.pool.reserve_n[0]) - 1
        if spare > 0:
            w.pool.refill(0, spare)                  # reserve -> worker 0's free list
        code, n = real(*args)
        seen.append((int(code), int(w.round_state[RS_PHASE]), int(w.round_state[RS_STATUS])))
        return code, n

    monkeypatch.setattr(w.eng, "drain_small_rounds", starved)
    t0 = run.start_us - run.warmup_us
    run_step(w, t0, t0 + run.engine.step_us)
    assert (DR_PYTHON, PH_ADMIT, ADM_NODES) in seen   # the forced path really ran
    assert w.pending_creations() == 0
    for t in [e.name for e in w.plan.events]:
        ra, rb = records_of(base, t), records_of(w, t)
        assert all(np.array_equal(ra[k], rb[k]) for k in ra), t


def test_many_small_admission_batches_stay_compiled(monkeypatch):
    """S1 Codex CX3's workload (60 round trips x 3 creations in one step, slabs flushed
    mid-step), replacing S1's `created_rows_indexed` test: every creation is admitted once, and
    admission never leaves the compiled loop."""
    run = make_run("spawn", ["create_on_answer=1", "rounds=60"], slab_bytes=2048,
                   parallel_min_partitions=10**9)
    w = World.build(run, threads=1)
    w.init_shards()
    real, seen = w.eng.drain_small_rounds, []

    def spy(*args):
        code, n = real(*args)
        seen.append((int(code), int(w.round_state[RS_PHASE])))
        return code, n

    monkeypatch.setattr(w.eng, "drain_small_rounds", spy)
    t0 = run.start_us - run.warmup_us
    stats = run_step(w, t0, t0 + run.engine.step_us)
    assert int(w.R[RT_ADM][0]) == 3 * 60 and w.pending_creations() == 0
    assert stats.compiled_rounds >= 60
    assert (DR_PYTHON, PH_ADMIT) not in seen
