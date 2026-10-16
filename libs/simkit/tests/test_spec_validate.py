import dataclasses

import pytest

from neorisk_simkit.spec import dist
from neorisk_simkit.spec.caps import CAP_ITEMS, NODE_BYTES, BudgetError, check_budget, compute_caps
from neorisk_simkit.spec.project import load_project, resolve_run
from neorisk_simkit.spec.validate import validate


@pytest.fixture
def run(fixture_project):
    return resolve_run(load_project(fixture_project("mini")), "sample", [])


def _with_boundary(run, name, **changes):
    plan = run.plan
    bs = tuple(dataclasses.replace(b, **changes) if b.name == name else b for b in plan.boundaries)
    return dataclasses.replace(run, plan=dataclasses.replace(plan, boundaries=bs))


def _with_kernel(run, proc, **changes):
    plan = run.plan
    ps = tuple(dataclasses.replace(p, kernel=dataclasses.replace(p.kernel, **changes))
               if p.name == proc else p for p in plan.processes)
    return dataclasses.replace(run, plan=dataclasses.replace(plan, processes=ps))


def test_mini_is_valid(run):
    rep = validate(run)
    assert rep.ok, rep.errors
    assert [c.name for c in rep.caps] == list(CAP_ITEMS)


def test_zero_latency_boundary_is_an_error(run):
    bad = _with_boundary(run, "take", latency=dist.constant(ms=0), min_latency_us=0)
    assert "boundary take: minimum latency must be > 0" in validate(bad).errors


def test_cross_partition_write_is_an_error(run):
    bad = _with_kernel(run, "bin_desk", state="user")
    errs = validate(bad).errors
    assert any("process bin_desk runs in partition 'bin' but its kernel state is 'user'" in e
               for e in errs)


def test_reserving_foreign_or_unknown_records_is_an_error(run):
    from neorisk_simkit.engine import Res
    bad = _with_kernel(run, "user_main", max=Res(records={"item_taken": 1, "nope": 1}))
    errs = validate(bad).errors
    assert any("user_main reserves records of 'item_taken' owned by partition 'bin'" in e
               for e in errs)
    assert any("user_main reserves unknown record type 'nope'" in e for e in errs)


def test_start_command_without_start_trigger_and_bad_command_ids(run):
    bad = _with_kernel(run, "bin_desk", commands=(0, 1))
    assert any("bin_desk handles START but has no start= or every=" in e
               for e in validate(bad).errors)


def test_caps_formulas(run):
    caps = {c.name: c for c in compute_caps(run)}
    from neorisk_simkit.spec.caps import slabs_per_worker
    spw = slabs_per_worker(run.plan)
    assert spw == 5 + 0 + 2 + 1
    assert caps["output_slabs"].hard_bytes == run.budget.threads * spw * run.engine.slab_bytes
    assert caps["merge_working_space"].hard_bytes == 2 * caps["step_output"].hard_bytes
    assert caps["timer_heaps"].hard_bytes == run.engine.timer_nodes * NODE_BYTES == 100_000 * 40
    assert caps["checker_state"].hard_bytes == 0 and caps["scorer"].hard_bytes == 0
    assert all(c.estimate_bytes <= c.hard_bytes for c in caps.values())


def test_hidden_bytes_follow_the_world_dtype_table(run):
    import numpy as np

    from neorisk_simkit.engine.world import HIDDEN_DTYPES, hidden_bytes
    from neorisk_simkit.spec import caps as caps_mod
    per = {1: 1, "A": 3, "N_NS": 2}
    expect = sum(np.dtype(dt).itemsize * per[m] for _, dt, m in HIDDEN_DTYPES)
    assert hidden_bytes(3, 2) == expect == 9 * 8 + 4 * 5 + 2 + 1 + 4 * 3 + 4 * 2
    names = [n for n, _, _ in HIDDEN_DTYPES]
    assert "susp_t" in names and "susp_delta" in names and len(names) == len(set(names))
    assert caps_mod.hidden_bytes(run.plan) == hidden_bytes(1, len(run.plan.namespaces))


def test_forced_timer_capacity_below_a_kernel_maximum_is_an_error(run):
    bad = dataclasses.replace(run, engine=dataclasses.replace(
        run.engine, force_capacity={"timers": 0}))
    assert any("force_capacity timers=0 is below the declared maximum timers=1 of user_main" in e
               for e in validate(bad).errors)
    ok = dataclasses.replace(run, engine=dataclasses.replace(
        run.engine, force_capacity={"timers": 1}))
    assert validate(ok).ok


def test_budget_refusal_names_items(run):
    small = dataclasses.replace(run, budget=dataclasses.replace(run.budget, memory_bytes=1024))
    with pytest.raises(BudgetError, match="exceed the memory budget") as e:
        check_budget(compute_caps(small), small.budget)
    assert "step_output" in str(e.value) and "timer_heaps" in str(e.value)
    assert not validate(small).ok


def test_every_on_an_owner_process_is_an_error(run):
    plan = run.plan
    ps = tuple(dataclasses.replace(p, every_us=3_600_000_000) if p.name == "user_main" else p
               for p in plan.processes)
    bad = dataclasses.replace(run, plan=dataclasses.replace(plan, processes=ps))
    assert any("user_main: every= is only for shard processes (D26)" in e
               for e in validate(bad).errors)


def _with_table_col(run, table, col, ltype):
    plan = run.plan
    ts = tuple(
        dataclasses.replace(t, cols=tuple(
            dataclasses.replace(c, ltype=ltype) if c.name == col else c for c in t.cols))
        if t.name == table else t for t in plan.tables)
    return dataclasses.replace(run, plan=dataclasses.replace(plan, tables=ts))


@pytest.mark.parametrize("maker,name", [("i32", "i32"), ("i16", "i16")])
def test_nullable_narrow_int_owner_state_is_an_error(run, maker, name):
    from neorisk_simkit.spec import types
    bad = _with_table_col(run, "user", "balance", types.opt(getattr(types, maker)()))
    assert f"user.balance: nullable {name} state is not supported; use opt(i64)" in \
        validate(bad).errors


def test_nullable_i64_and_non_null_narrow_owner_state_are_fine(run):
    from neorisk_simkit.spec import types
    ok1 = _with_table_col(run, "user", "balance", types.opt(types.i64()))
    ok2 = _with_table_col(run, "user", "balance", types.i32())
    for r in (ok1, ok2):
        assert not any("nullable" in e for e in validate(r).errors)
