"""Spec §10 exit test: memory caps are enforced. A run whose caps exceed the budget is refused
up front; a run that hits a cap fails with the item named and leaves no dataset."""

import pytest
from conftest import FIXTURES, make_run

from neorisk_simkit.engine import CapExceeded
from neorisk_simkit.engine.run import Simulation
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


@pytest.mark.parametrize("override,limit", [("budget.max_step_rows=50", 50),
                                            ("budget.max_step_bytes=4096", 4096)])
def test_step_output_cap_fails_while_the_step_accumulates(override, limit):
    """The step cap is checked as slabs are flushed, so a runaway step fails after at most one
    more flush past the cap, not after the whole step is collected and merged."""
    run = make_run("mini", ["users=2000", override], slab_bytes=1024)
    sim = Simulation(run, threads=1)
    slab = sim.world.slabs[0]
    per_flush_rows = int(sum(slab.cap))
    per_flush_bytes = sum(a.nbytes for bufs in slab.buffers.values() for a in bufs.values())
    whole_step = make_run("mini", ["users=2000"], slab_bytes=1024)
    first = next(Simulation(whole_step, threads=1).steps()).stats
    unit = "rows" if "rows" in override else "bytes"
    assert first[unit] > 4 * (limit + (per_flush_rows if unit == "rows" else per_flush_bytes))
    with pytest.raises(CapExceeded) as e:
        next(sim.steps())
    assert e.value.item == "step_output" and e.value.limit == limit
    assert e.value.attempted <= limit + (per_flush_rows if unit == "rows" else per_flush_bytes)


def test_step_output_counts_id_allocations():
    """`p.ids` rows have no entity table but sit in the step's buffers until it seals."""
    first = next(Simulation(make_run("mini"), threads=1).steps()).stats
    assert first["rows"] > 0                    # records + created entity rows, ids excluded
    capped = make_run("mini", [f"budget.max_step_rows={first['rows']}"])
    with pytest.raises(CapExceeded) as e:
        next(Simulation(capped, threads=1).steps())
    assert e.value.item == "step_output" and e.value.attempted > first["rows"]


def test_threads_override_is_validated_against_the_budget(tmp_path):
    """Caps are computed for the worker count the run allocates, not `budget.threads`."""
    run = make_run("mini")
    total = sum(c.hard_bytes for c in compute_caps(run))
    fits = [f"budget.memory={total}"]
    out = tmp_path / "over"
    with pytest.raises(ValidationFailed, match="exceed the memory budget") as e:
        run_to_dataset(MINI, "sample", fits, out_dir=out, threads=run.budget.threads + 8)
    assert "output_slabs" in str(e.value)
    assert not out.exists() and not out.with_suffix(".partial").exists()
    ok = run_to_dataset(MINI, "sample", fits, out_dir=tmp_path / "ok",
                        threads=run.budget.threads - 1)
    assert ok.stats["threads"] == run.budget.threads - 1


@pytest.mark.parametrize("threads", [0, -2])
def test_non_positive_threads_are_refused_at_validation(tmp_path, threads):
    out = tmp_path / "zero"
    with pytest.raises(ValidationFailed, match="threads must be >= 1"):
        run_to_dataset(MINI, "sample", [], out_dir=out, threads=threads)
    assert not out.exists() and not out.with_suffix(".partial").exists()


# ---------------------------------------------------------------------------- entity buffers
SMALL_STEPS = ["engine.step='15m'", "engine.adapt=false"]


def test_oversized_entity_row_groups_are_refused_at_validation(tmp_path):
    """The entity writer keeps up to one row group per table buffered across steps; with many
    small steps and a huge row group that buffer would hold almost the whole run, so the cap
    (`entity_buffers`) refuses the configuration up front."""
    out = tmp_path / "refused"
    with pytest.raises(ValidationFailed, match="exceed the memory budget") as e:
        run_to_dataset(MINI, "sample", [*SMALL_STEPS, "writer.row_group_rows=1_000_000_000"],
                       out_dir=out)
    assert "entity_buffers" in str(e.value)
    assert not out.exists() and not out.with_suffix(".partial").exists()


def test_entity_buffers_stay_within_their_cap(tmp_path, monkeypatch):
    """What the entity writer really buffers (Arrow bytes) never exceeds the reservation."""
    from neorisk_simkit.io import entities
    from neorisk_simkit.spec.caps import entity_buffer_bytes

    seen = []
    add = entities.EntityWriter.add

    def spy(self, tables):
        add(self, tables)
        seen.append(sum(s.buffered_bytes for s in self._streams.values()))

    monkeypatch.setattr(entities.EntityWriter, "add", spy)
    run = make_run("mini", SMALL_STEPS)
    run_to_dataset(MINI, "sample", SMALL_STEPS, out_dir=tmp_path / "ok")
    assert len(seen) > 100 and max(seen) > 0
    assert max(seen) <= entity_buffer_bytes(run.plan, run.writer.row_group_rows)[0]


def test_entity_buffer_cap_fails_at_runtime_with_the_item_named(tmp_path, monkeypatch):
    from neorisk_simkit.io import entities

    monkeypatch.setattr(entities, "entity_buffer_bytes", lambda plan, rows: (4096, 0))
    out = tmp_path / "capped"
    with pytest.raises(CapExceeded) as e:
        run_to_dataset(MINI, "sample", SMALL_STEPS, out_dir=out)
    assert e.value.item == "entity_buffers" and e.value.limit == 4096
    assert e.value.attempted > 4096
    assert not out.exists() and not out.with_suffix(".partial").exists()
