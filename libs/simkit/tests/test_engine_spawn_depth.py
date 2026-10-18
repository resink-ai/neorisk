"""D72 / F-04: spawn depth is a runtime counter per slot, bounded per creating process."""

import pytest
from conftest import FIXTURES, make_run

from neorisk_simkit.engine import CapExceeded
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.spec.validate import validate


def test_a_creation_cycle_validates():
    assert validate(make_run("recur")).ok


def test_bounded_recursion_runs(tmp_path):
    res = run_to_dataset(FIXTURES / "recur", "sample", [], out_dir=tmp_path / "r", threads=1)
    levels = sorted(read_events(res.out_dir)["grown"]["level"].to_list())
    assert levels == [1, 1, 2, 2, 3, 3]


def test_depth_beyond_the_process_limit_fails_naming_it(tmp_path):
    with pytest.raises(CapExceeded) as e:
        run_to_dataset(FIXTURES / "recur", "sample", ["levels=4"], out_dir=tmp_path / "r",
                       threads=1)
    assert (e.value.item, e.value.limit, e.value.attempted, e.value.process) == (
        "max_spawn_depth", 3, 4, "grow")


def test_a_process_without_a_limit_takes_the_budget_default():
    run = make_run("recur", ["budget.max_spawn_depth=5"])
    w = World.build(run, threads=1)
    plan = run.plan
    assert int(w.max_depth[plan.process("plant").action_id]) == 5
    assert int(w.max_depth[plan.process("grow").action_id]) == 3


def test_process_max_spawn_depth_must_be_positive():
    errs = validate(make_run("recur", ["max_depth=0"])).errors
    assert "grow: max_spawn_depth must be >= 1" in errs


def test_chain_fixture_fails_at_runtime_beyond_the_budget(tmp_path):
    with pytest.raises(CapExceeded) as e:
        run_to_dataset(FIXTURES / "chain", "sample", ["budget.max_spawn_depth=1"],
                       out_dir=tmp_path / "c", threads=1)
    assert e.value.item == "max_spawn_depth" and e.value.process == "b_main"
