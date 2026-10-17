import json

import numpy as np
import pytest
from conftest import FIXTURES, make_run

from neorisk_simkit.checks.structural import check_ref_range, ref_bounds
from neorisk_simkit.engine import EngineError
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.std import NULL


def test_range_check_skips_null_and_names_the_column():
    assert check_ref_range("event e.x", np.array([0, 3, NULL], np.int64), "item", 4) == 2
    with pytest.raises(EngineError, match=r"event e.x: ref 4 outside \[0, 4\) of item"):
        check_ref_range("event e.x", np.array([1, 4], np.int64), "item", 4)


def test_runs_count_checked_refs(tmp_path):
    r = run_to_dataset(FIXTURES / "mini", "sample", out_dir=tmp_path / "ok", threads=1)
    assert json.loads((r.out_dir / "manifest.json").read_text())["checks"]["ref_in_range"] > 0


def test_a_dangling_ref_fails_the_seal(tmp_path):
    with pytest.raises(EngineError, match=r"event spawned.acct_id: ref 1000 outside \[0, 3\) "
                                          r"of acct"):
        run_to_dataset(FIXTURES / "spawn", "sample", ["bad_ref=1"], out_dir=tmp_path / "x",
                       threads=1)


def test_population_refs_are_bounded_by_admitted_owners():
    """F-05: `ledger` has 6 accounts, 3 initial (initial 0.5); before any arrival only dense
    indices 0..2 exist, so the bound is 3, not 6."""
    run = make_run("ledger")
    w = World.build(run, threads=1)
    t0 = run.start_us - run.warmup_us
    w.admit_population(t0, t0 + 1)
    assert ref_bounds(w, {})["acct"] == 3
