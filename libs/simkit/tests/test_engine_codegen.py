import dataclasses

import numpy as np
import pytest

from neorisk_simkit.engine import AbiViolation, EngineError
from neorisk_simkit.engine.build import build_engine
from neorisk_simkit.engine.cmdq import NodePool, PayloadPool
from neorisk_simkit.engine.identity import handle_ns, handle_ordinal, handle_slot, is_provisional
from neorisk_simkit.engine.layout import make_ctx
from neorisk_simkit.engine.slabs import SlabSet
from neorisk_simkit.engine.world import allocate_hidden
from neorisk_simkit.spec.project import load_project, resolve_run

NULL = -(2**63)


@pytest.fixture
def run(fixture_project):
    return resolve_run(load_project(fixture_project("mini")), "sample", [])


def _setup(run, checked=False, force=None):
    if force:
        run = dataclasses.replace(run, engine=dataclasses.replace(run.engine, force_capacity=force))
    gen = build_engine(run.plan, checked=checked)
    hidden, _ = allocate_hidden(run.plan, run)
    pool, pay = NodePool(1000, 1), PayloadPool(100, 1)
    pool.refill(0, 500)
    pay.refill(0, 50)
    slab = SlabSet(run.plan, run.engine, worker=0)
    return gen, hidden, pool, slab, slab.as_tuple(hidden, pool, pay)


def _ctx(g=3, t=1_000, lamport=4, pid=(1 << 56) | 3, action=0):
    return make_ctx(t, 3, pid, g, 11, action, 0, np.zeros(33, np.int64), 7, (), (), (), lamport, 0)


def test_build_is_cached_by_content(run):
    a, b = build_engine(run.plan), build_engine(run.plan)
    assert a.__file__ == b.__file__ and a.RESOURCES == [
        "records:user_joined", "records:ping", "records:took", "records:item_taken",
        "records:take_failed", "creates:note", "creates:visit", "timers", "requests"]
    assert build_engine(run.plan, checked=True).__file__ != a.__file__


def test_reserve_and_emit_until_slab_is_full(run):
    gen, hidden, _, slab, out = _setup(run, force={"records:ping": 2})
    vec = np.array([0, 1, 0, 0, 0, 0, 0, 0, 0], np.int64)
    ctx = _ctx()
    for n in range(2):
        assert gen._reserve_user_main(out, vec)
        gen._emit_ping(out, ctx, 1_000, 3, 77, n, NULL)
    assert not gen._reserve_user_main(out, vec)
    assert slab.miss[0] == slab.resources.index("records:ping")
    chunk = slab.flush()
    ping = chunk.records["ping"]
    assert ping["seq"].tolist() == [0, 1] and ping["lamport"].tolist() == [4, 4]
    assert ping["n"].tolist() == [0, 1] and ping["valid_note_id"].tolist() == [0, 0]
    assert ping["pid"].tolist() == [(1 << 56) | 3] * 2 and ping["action"].tolist() == [0, 0]
    assert hidden.rseq[3] == 2
    assert gen._reserve_user_main(out, vec)          # flush made room again


def test_checked_mode_catches_emit_without_reservation(run):
    gen, _, _, _, out = _setup(run, checked=True)
    with pytest.raises(AbiViolation, match="emit beyond reservation: ping"):
        gen._emit_ping(out, _ctx(), 1_000, 3, 77, 0, NULL)


def test_emit_time_must_equal_ctx_t(run):
    gen, _, _, _, out = _setup(run)
    gen._reserve_user_main(out, np.array([0, 1, 0, 0, 0, 0, 0, 0, 0], np.int64))
    with pytest.raises(EngineError, match="records must be emitted at ctx.t"):
        gen._emit_ping(out, _ctx(), 999, 3, 77, 0, NULL)


def test_create_and_new_id_return_provisional_handles(run):
    gen, _, _, slab, out = _setup(run)
    gen._reserve_user_main(out, np.array([0, 0, 0, 0, 0, 1, 2, 0, 0], np.int64))
    h1 = gen._create_note(out, _ctx(), 5)
    v1, v2 = gen._new_id(out, _ctx(), 1), gen._new_id(out, _ctx(), 1)
    assert is_provisional(h1) and handle_ns(h1) == 0 and handle_slot(h1) == 3
    assert [handle_ordinal(v) for v in (v1, v2)] == [0, 1] and handle_ns(v1) == 1
    chunk = slab.flush()
    assert chunk.creates["note"]["size"].tolist() == [5]
    assert chunk.creates["visit"]["ordinal"].tolist() == [0, 1]


def test_timer_rules(run):
    gen, hidden, pool, _, out = _setup(run)
    gen._reserve_user_main(out, np.array([0, 0, 0, 0, 0, 0, 0, 1, 0], np.int64))
    gen._timer(out, _ctx(), 5_000, 1, 5, 0)
    head = hidden.qhead[3]
    assert head >= 0 and pool.time[head] == 5_000 and pool.key[head] == (5 << 56) | 4
    assert hidden.cseq[3] == 1
    with pytest.raises(EngineError, match="timer scheduled before current time"):
        gen._timer(out, _ctx(), 999, 1, 5, 0)


def test_request_bounds_and_outbox_row(run):
    gen, _, _, slab, out = _setup(run)
    gen._reserve_user_main(out, np.array([0, 0, 0, 0, 0, 0, 0, 0, 1], np.int64))
    gen._request_take(out, _ctx(), 1_000, 2, 99, 17)
    ob = slab.outbox_view()
    assert ob["kind"].tolist() == [1] and ob["dst"].tolist() == [2] and ob["tag"].tolist() == [99]
    assert ob["pay"][0, 0] == 17 and ob["pay"][0, 7] == 3 and slab.req_count[0] == 1
    with pytest.raises(EngineError, match="user_main: request take to shard 9 but bin has 4"):
        gen._request_take(out, _ctx(), 1_000, 9, 99, 17)


def test_hidden_arrays_match_the_cap_table(run):
    from neorisk_simkit.engine.world import HIDDEN_DTYPES
    from neorisk_simkit.spec.caps import hidden_bytes
    hidden, slot_base = allocate_hidden(run.plan, run)
    G = len(hidden.pid)
    assert G == 200 + 4 and slot_base == {"user": 0, "bin": 200}
    assert sum(getattr(hidden, n).nbytes for n, _, _ in HIDDEN_DTYPES) == G * hidden_bytes(run.plan)
    assert hidden.susp_t.dtype == np.int64 and hidden.susp_delta.dtype == np.int64


def test_dispatch_runs_the_kernels_end_to_end(run):
    """Pins the dispatch contract: per-action cfg/reads/refs in ctx, world_state per process."""
    gen, hidden, _, slab, out = _setup(run)
    hidden.lslot[:200] = np.arange(200)
    hidden.lslot[200:] = np.arange(4)
    user = (np.zeros(200, np.int16), np.zeros(200, np.int64), np.full(200, NULL, np.int64))
    loc = (np.zeros(200, np.int32), np.zeros(200, np.int64))
    offs, on_hand = np.arange(0, 41, 10, dtype=np.int64), np.ones(40, np.int32)
    ws = ((hidden.lslot, user, loc), (hidden.lslot, offs, np.arange(40, dtype=np.int64),
                                      (on_hand,)))
    reads = (np.repeat(np.arange(4), 10).astype(np.int32), np.arange(40, dtype=np.int64),
             np.tile(np.arange(10), 4).astype(np.int64))
    cfg = (((1, 3.6e9, 0.0, 0.0), 1.0, 1.0, 50), ())          # take_p = note_p = 1
    kc, nopay = np.zeros(33, np.int64), np.zeros((1, 12), np.int64)

    def ctx(g, t, action, lamport):
        kc[0] = 0
        return make_ctx(t, g, (1 << 56) | g, g, 11, action, 0, kc, 7, cfg, (reads, reads),
                        ((), ()), lamport, 0)

    assert gen.dispatch(0, ctx(3, 1_000, 0, 5), (0, 0, 1_000, 0, 0, nopay, 0), ws, out) == 0
    assert gen.dispatch(0, ctx(3, 1_000, 0, 6), (1, 0, 1_000, 0, 0, nopay, 0), ws, out) == 0
    req = slab.outbox_view()
    item = req["pay"][0, 0]
    assert req["kind"].tolist() == [1] and req["dst"][0] == item // 10
    assert user[2][3] != NULL and loc[0][3] == 1                     # note created, ping counted
    shard = 200 + int(req["dst"][0])
    cmd = (1, req["tag"][0], 1_000, 0, 0, req["pay"], 0)
    assert gen.dispatch(1, ctx(shard, 1_000, 1, 9), cmd, ws, out) == 0
    resp = slab.outbox_view()
    assert resp["kind"].tolist() == [1, 3] and resp["time"][1] == 1_000 + 200_000
    assert resp["dst"][1] == 3 and resp["resp_kind"][1] == 2 and resp["target_action"][1] == 0
    assert on_hand[item] == 0
    chunk = slab.flush()
    assert chunk.records["item_taken"]["left"].tolist() == [0]
    assert [len(chunk.records[e]["time"]) for e in ("user_joined", "ping")] == [1, 1]
