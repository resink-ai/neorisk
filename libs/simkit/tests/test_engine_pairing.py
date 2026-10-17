"""D39 explicit response tagging and D40 request/response pairing."""

import json

import numpy as np
import pytest
from conftest import FIXTURES, make_run, records_of

from neorisk_simkit.engine import EngineError
from neorisk_simkit.engine.cmdq import PAY_KIND, NodePool, PayloadPool, q_push
from neorisk_simkit.engine.rounds import run_step
from neorisk_simkit.engine.route import resume_owner
from neorisk_simkit.engine.slabs import OB_MESSAGE, OB_RESPONSE
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset


def _step(overrides=()):
    run = make_run("pairing", overrides)
    w = World.build(run, threads=1)
    t0 = run.start_us - run.warmup_us
    run_step(w, t0, t0 + run.engine.step_us)
    return run, w


def test_resume_owner_reads_the_delivered_kind():
    P, PA = NodePool(8, 1), PayloadPool(8, 1)
    P.refill(0, 8)
    t = P.as_tuple()
    qhead = np.full(1, -1, np.int32)
    q_push(t, 0, qhead, 0, 5, 5, 0, 0, 1, 0, 0, -1)          # a timer at 5 (kind 1)
    PA.rows[0, PAY_KIND] = OB_MESSAGE
    q_push(t, 0, qhead, 0, 7, 1, 0, 1, 2, 0, 0, 0)           # a message at 7 (kind 2)
    PA.rows[1, PAY_KIND] = OB_RESPONSE
    q_push(t, 0, qhead, 0, 9, 1, 0, 2, 3, 0, 0, 1)           # a response at 9 (kind 3)
    resume_owner(t, PA.rows, qhead, 0)
    order, node = [], qhead[0]
    while node >= 0:
        order.append((int(P.kind[node]), int(P.time[node])))
        node = P.next[node]
    # only the response is a response: it runs first, then the earlier commands at T_r = 9
    assert order == [(3, 9), (1, 9), (2, 9)]


def test_answered_requests_pair_up():
    _, w = _step()
    assert len(records_of(w, "answered")["time"]) == 2
    assert w.stats["pairing"] == {"ask": {"requests": 2, "responses": 2}}


@pytest.mark.parametrize("mode,match", [
    (1, r"desk_main: request ask must be answered exactly once \(answered 0, returned 2\)"),
    (2, r"desk_main: request ask must be answered exactly once \(answered 2, returned 0\)"),
    (3, r"desk_main: message tick answered a request it was not given"),
])
def test_unpaired_answers_fail_naming_process_and_boundary(mode, match):
    with pytest.raises(EngineError, match=match):
        _step([f"mode={mode}"])


def test_unpaired_answers_cite_partition_seq_and_action():
    """§11: "Failures cite (partition_id, seq) and action ID" (F-06)."""
    with pytest.raises(EngineError, match=r"\(answered 0, returned 2\) at \(partition_id \d+\), "
                                          r"sent by \(partition_id \d+, seq \d+\), "
                                          r"action \d+$"):
        _step(["mode=1"])


def test_manifest_reports_pairing(tmp_path):
    r = run_to_dataset(FIXTURES / "pairing", "sample", out_dir=tmp_path / "run", threads=1)
    m = json.loads((r.out_dir / "manifest.json").read_text())
    assert m["pairing"] == {"ask": {"requests": 2, "responses": 2}}


def test_existing_fixtures_still_pair():
    for name in ("mini", "spawn", "trace_shopper", "blocking", "ordering"):
        run = make_run(name)
        w = World.build(run, threads=1)
        w.init_shards()
        t0 = run.start_us - run.warmup_us
        run_step(w, t0, t0 + run.engine.step_us)
        for b, c in w.stats["pairing"].items():
            assert c["responses"] <= c["requests"], (name, b)
