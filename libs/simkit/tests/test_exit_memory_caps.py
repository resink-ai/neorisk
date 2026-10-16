"""Spec §10 exit test: memory caps are enforced. A run whose caps exceed the budget is refused
up front; a run that hits a cap fails with the item named and leaves no dataset."""

import pytest
from conftest import FIXTURES

from neorisk_simkit.engine import CapExceeded
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import ValidationFailed, run_to_dataset
from neorisk_simkit.spec.caps import compute_caps
from neorisk_simkit.spec.project import load_project, resolve_run

MINI = FIXTURES / "mini"


def test_over_budget_run_is_refused_before_anything_is_written(tmp_path):
    out = tmp_path / "refused"
    with pytest.raises(ValidationFailed, match="exceed the memory budget") as e:
        run_to_dataset(MINI, "sample", ["budget.memory='1MB'"], out_dir=out)
    assert "timer_heaps" in str(e.value) and "step_output" in str(e.value)
    assert not out.exists() and not out.with_suffix(".partial").exists()


@pytest.mark.parametrize("project,overrides,item", [
    (MINI, ["engine.timer_nodes=40"], "timer_heaps"),
    (MINI, ["budget.max_step_rows=20"], "step_output"),
    (MINI, ["max_live=50"], "live_partition_state"),
    (MINI, ["behavior.take_p=1.0", "engine.max_messages_per_step=1"], "requests_and_inboxes"),
    (FIXTURES / "trace_shopper", ["budget.max_admissions_per_step=0"],
     "max_admissions_per_step"),
])
def test_runtime_caps_fail_with_the_item_named(tmp_path, project, overrides, item):
    out = tmp_path / "capped"
    with pytest.raises(CapExceeded) as e:
        run_to_dataset(project, "sample", overrides, out_dir=out)
    assert e.value.item == item and item in str(e.value)
    if item == "max_admissions_per_step":                 # spec §06: names the process
        assert str(e.value).endswith("in process journey")
    assert not out.exists() and not out.with_suffix(".partial").exists()


def test_slab_allocation_stays_within_its_cap():
    run = resolve_run(load_project(MINI), "sample", [])
    caps = {c.name: c for c in compute_caps(run)}
    w = World.build(run, threads=run.budget.threads)
    assert w.allocated_slab_bytes() <= caps["output_slabs"].hard_bytes


def test_estimates_and_caps_are_reported_separately():
    run = resolve_run(load_project(MINI), "sample", [])
    caps = {c.name: c for c in compute_caps(run)}
    assert caps["step_output"].estimate_bytes < caps["step_output"].hard_bytes
