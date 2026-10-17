import json
from types import SimpleNamespace

import numpy as np
import pytest
from conftest import FIXTURES, make_run

from neorisk_simkit.checks.structural import check_ref_range, check_refs, ref_bounds
from neorisk_simkit.engine import EngineError
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.spec.types import COMMON_COLUMNS
from neorisk_simkit.std import NULL


def test_range_check_skips_null_and_names_the_column():
    assert check_ref_range("event e.x", np.array([0, 3, NULL], np.int64), "item", 4) == 2
    with pytest.raises(EngineError, match=r"event e.x: ref 4 outside \[0, 4\) of item"):
        check_ref_range("event e.x", np.array([1, 4], np.int64), "item", 4)


def test_runs_count_checked_refs(tmp_path):
    r = run_to_dataset(FIXTURES / "mini", "sample", out_dir=tmp_path / "ok", threads=1)
    assert json.loads((r.out_dir / "manifest.json").read_text())["checks"]["ref_in_range"] > 0


@pytest.mark.parametrize("on_answer", [0, 1])
def test_a_dangling_ref_fails_the_seal(tmp_path, on_answer):
    with pytest.raises(EngineError, match=r"event spawned.acct_id: ref 1000 outside \[0, 3\) "
                                          r"of acct at \(partition_id \d+, seq \d+\), "
                                          r"action \d+"):
        run_to_dataset(FIXTURES / "spawn", "sample",
                       ["bad_ref=1", f"create_on_answer={on_answer}"],
                       out_dir=tmp_path / "x", threads=1)


def test_a_ref_to_a_table_with_no_rows_dangles():
    col = SimpleNamespace(name="x", ltype=SimpleNamespace(kind="ref", target="ghost",
                                                          nullable=False))
    plan = SimpleNamespace(events=[SimpleNamespace(name="e", group="events",
                                                   cols=[None] * len(COMMON_COLUMNS) + [col])],
                           change_groups=[], namespaces=(), tables=())
    rows = {"x": np.array([NULL, 0], np.int64), "pid": np.array([5, 6], np.int64),
            "seq": np.array([1, 2], np.int32), "action": np.array([3, 4], np.int16)}
    with pytest.raises(EngineError, match=r"ref 0 outside \[0, 0\) of ghost at "
                                          r"\(partition_id 6, seq 2\), action 4"):
        check_refs(plan, {"e": rows}, {}, {})


def test_population_refs_are_bounded_by_admitted_owners():
    """F-05: `ledger` has 6 accounts, 3 initial (initial 0.5); before any arrival only dense
    indices 0..2 exist, so the bound is 3, not 6."""
    run = make_run("ledger")
    w = World.build(run, threads=1)
    t0 = run.start_us - run.warmup_us
    w.admit_population(t0, t0 + 1)
    assert ref_bounds(w, {})["acct"] == 3
