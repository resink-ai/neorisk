import dataclasses
import itertools

import numpy as np
import pyarrow.compute as pc
import pytest
from conftest import make_run

from neorisk_simkit.engine import CapExceeded
from neorisk_simkit.engine.run import Simulation, next_step_length

H = 3_600_000_000


def _sim(overrides=(), **engine):
    run = make_run("mini", overrides, **engine)
    return run, Simulation(run, threads=2)


def test_steps_cover_the_window_with_a_boundary_at_start():
    run, sim = _sim(step_us=4 * H)
    steps = list(sim.steps())
    t0, end = run.start_us - run.warmup_us, run.start_us + run.span_us
    assert steps[0].t_start == t0 and steps[-1].t_end == end
    assert all(a.t_end == b.t_start for a, b in itertools.pairwise(steps))
    assert any(s.t_end == run.start_us for s in steps)
    assert all(not s.exported for s in steps if s.t_end <= run.start_us)
    for s in steps:
        assert all(t.num_rows == 0 for t in s.events.values()) or s.exported


def test_events_are_canonical_and_ids_public():
    _, sim = _sim()
    seen = set()
    for s in sim.steps():
        for t in s.events.values():
            if t.num_rows == 0:
                continue
            key = np.lexsort([t["seq"].to_numpy(), t["partition_id"].to_numpy(),
                              t["lamport"].to_numpy(),
                              t["event_time"].cast("int64").to_numpy()])
            assert (key == np.arange(t.num_rows)).all()
            ids = t["event_id"].to_numpy()
            assert (ids > 0).all() and not (set(ids.tolist()) & seen)
            seen |= set(ids.tolist())
            assert t["cause_id"].null_count == t.num_rows
            assert t.column_names[:8] == ["event_id", "event_type", "event_time", "lamport",
                                          "partition_id", "seq", "cause_id", "action_id"]


def test_created_rows_get_contiguous_dense_ids_and_refs_resolve():
    _, sim = _sim(["behavior.note_p=0.5"])
    notes, refs = [], []
    for s in sim.steps():
        if "note" in s.entities:
            notes.extend(s.entities["note"]["id"].to_pylist())
        ping = s.events.get("ping")
        if ping is not None and ping.num_rows:
            refs.extend(x for x in ping["note_id"].to_pylist() if x is not None)
    assert notes and len(set(notes)) == len(notes)
    assert set(refs) <= set(notes)                   # cross-step references resolve


def test_static_entities():
    _, sim = _sim()
    ents = sim.static_entities()
    assert ents["user"].num_rows == 200 and ents["item"].num_rows == 40
    assert set(ents["user"]["origin"].to_pylist()) == {"initial", "arrival"}
    assert ents["user"].column_names[:3] == ["id", "created_at", "origin"]


def test_boundary_instants():
    run, sim = _sim(step_us=6 * H)
    for s in sim.steps():
        for t in s.events.values():
            if t.num_rows:
                times = pc.cast(t["event_time"], "int64").to_numpy()
                assert times.min() >= s.t_start and times.max() < s.t_end
                assert times.min() >= run.start_us


def test_step_output_cap():
    run = make_run("mini")
    run2 = dataclasses.replace(run, budget=dataclasses.replace(run.budget, max_step_rows=10))
    with pytest.raises(CapExceeded, match="step_output"):
        list(Simulation(run2, threads=1).steps())


def test_next_step_length_targets_quarter_of_cap():
    run, _ = _sim()
    eng, bud = run.engine, dataclasses.replace(run.budget, max_step_rows=1000)
    assert next_step_length(4 * H, 500, eng, bud) == 2 * H        # 25% of 1000 = 250 rows
    assert next_step_length(4 * H, 0, eng, bud) == eng.step_max_us
    assert next_step_length(4 * H, 10**9, eng, bud) == eng.step_min_us


def test_stats_carry_engine_counters():
    _, sim = _sim(["behavior.max_pings=1", "behavior.take_p=0.0"])
    steps = list(sim.steps())
    st = sim.stats
    assert st["steps"] == len(steps) and len(st["rounds_per_step"]) == len(steps)
    assert 0 < st["rejects"]["user_main"] <= 200 and isinstance(st["retries"], int)
    assert isinstance(st["late_messages"], int) and isinstance(st["continuations"], int)


def test_retired_slots_are_reused_after_seal():
    # 200 users through 150 live slots: arrivals only fit once retired owners are freed
    _, sim = _sim(["behavior.max_pings=1", "behavior.take_p=0.0", "max_live=150"])
    freed = sum(s.stats["freed_slots"] for s in sim.steps())
    assert freed >= 50 and sim.stats["rejects"]["user_main"] == freed


def test_owner_dense_ranks_by_creation_key_and_solves_provisional_creators():
    """Created owners rank by (created_at, commit lamport, creator pid, ordinal), whatever the
    row order; a creator created this step (provisional pid) ranks by its final pid, which
    `_owner_dense` solves for (here row order is the reverse of the final order)."""
    from neorisk_simkit.engine.identity import make_handle
    from neorisk_simkit.io.seal import _owner_dense

    pop = (1 << 56) | 4                                   # a population creator (dense pid)
    p0, p1 = make_handle(0, 7, 0), make_handle(0, 7, 1)   # two pays, one commit of `pop`
    r0, r1 = make_handle(1, 9, 0), make_handle(1, 3, 0)   # one refund per pay, same lamport
    i64 = lambda *v: np.array(v, np.int64)
    creates = {
        "pay": {"handle": i64(p1, p0), "pid": i64(pop, pop), "ordinal": i64(1, 0),
                "created_at": i64(10, 10)},
        "refund": {"handle": i64(r1, r0), "pid": i64(p1, p0), "ordinal": i64(0, 0),
                   "created_at": i64(10, 10)},
    }
    causes = (i64(p0, p1, r0, r1), i64(5, 5, 6, 6))
    dense = _owner_dense(creates, {"pay": 2, "refund": 3}, causes, {"pay": 100})
    assert dense["pay"].tolist() == [101, 100]
    assert dense["refund"].tolist() == [1, 0]           # r0 (creator p0 = 100) ranks first
