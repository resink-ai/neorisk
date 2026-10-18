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
    assert caps["timer_heaps"].hard_bytes == run.engine.timer_nodes * NODE_BYTES == 100_000 * 74
    assert caps["checker_state"].hard_bytes == 0 and caps["scorer"].hard_bytes == 0
    assert all(c.estimate_bytes <= c.hard_bytes for c in caps.values())
    from neorisk_simkit.engine.admit import CreationQueue
    from neorisk_simkit.spec.caps import OUTBOX_ROW_BYTES, PAYLOAD_W
    assert caps["requests_and_inboxes"].hard_bytes == (
        run.engine.max_messages_per_step * OUTBOX_ROW_BYTES
        + run.engine.payload_slots * 8 * PAYLOAD_W
        + run.budget.max_admissions_per_step * CreationQueue.row_bytes)


def test_hidden_bytes_follow_the_world_dtype_table(run):
    import numpy as np

    from neorisk_simkit.engine.world import HIDDEN_DTYPES, hidden_bytes
    from neorisk_simkit.spec import caps as caps_mod
    per = {1: 1, "A": 3, "N_NS": 2}
    expect = sum(np.dtype(dt).itemsize * per.get(m, m) for _, dt, m in HIDDEN_DTYPES)
    assert hidden_bytes(3, 2) == expect == 9 * 8 + 4 * 5 + 2 + 1 + 4 * 3 + 4 * 2 + 8 * 4 + 1
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


def test_nullable_cat_owner_state_is_an_error(run):
    from neorisk_simkit.spec import types
    bad = _with_table_col(run, "user", "tier", types.opt(types.cat("a", "b")))
    assert "user.tier: nullable cat state is not supported; use opt(i64)" in validate(bad).errors


def test_nullable_f64_owner_state_is_fine(run):
    from neorisk_simkit.spec import types
    ok = _with_table_col(run, "user", "balance", types.opt(types.f64()))
    assert not any("nullable" in e for e in validate(ok).errors)


def _renamed(cols, old, new):
    return tuple(dataclasses.replace(c, name=new) if c.name == old else c for c in cols)


@pytest.mark.parametrize("table,col,head", [("user", "tier", "origin"), ("note", "size", "id"),
                                            ("item", "price", "created_at")])
def test_a_table_column_may_not_shadow_the_entity_head(run, table, col, head):
    plan = run.plan
    ts = tuple(dataclasses.replace(t, cols=_renamed(t.cols, col, head)) if t.name == table
               else t for t in plan.tables)
    bad = dataclasses.replace(run, plan=dataclasses.replace(plan, tables=ts))
    assert (f"table {table}: column {head!r} shadows the reserved entity column {head!r} "
            "(entities/ write id, created_at, origin first)") in validate(bad).errors


@pytest.mark.parametrize("head", ["event_id", "lamport", "action_id"])
def test_an_event_column_may_not_shadow_the_common_columns(run, head):
    plan = run.plan
    es = tuple(dataclasses.replace(e, cols=e.cols[:8] + _renamed(e.cols[8:], "tier", head))
               if e.name == "user_joined" else e for e in plan.events)
    bad = dataclasses.replace(run, plan=dataclasses.replace(plan, events=es))
    assert (f"event user_joined: column {head!r} shadows the reserved common column "
            f"{head!r}") in validate(bad).errors


def test_a_change_group_column_may_not_shadow_the_history_head(run):
    from neorisk_simkit.spec.plan import ChangeGroupDef, Column
    from neorisk_simkit.spec.types import i32
    g = ChangeGroupDef("user_seq", 99, "user", (Column("seq", i32()),))
    bad = dataclasses.replace(run, plan=dataclasses.replace(
        run.plan, change_groups=(*run.plan.change_groups, g)))
    assert ("change group user_seq: column 'seq' shadows the reserved history column 'seq'"
            in validate(bad).errors)


def test_mini_shadows_no_head_column(run):
    assert not any("shadows the reserved" in e for e in validate(run).errors)


def _with_namespaces(run, n):
    extra = tuple(f"x{i}" for i in range(n - len(run.plan.namespaces)))
    return dataclasses.replace(run, plan=dataclasses.replace(
        run.plan, namespaces=run.plan.namespaces + extra))


def test_handle_layout_fits_64_namespaces_and_ns_64_would_alias_ns_0():
    from neorisk_simkit.engine import identity as ident
    assert ident.MAX_NAMESPACES == 64
    hs = {ident.make_handle(ns, 3, 5) for ns in range(ident.MAX_NAMESPACES)}
    assert len(hs) == 64 and all(ident.handle_ns(h) < 64 for h in hs)
    assert ident.make_handle(64, 3, 5) == ident.make_handle(0, 3, 5)   # why 65 is refused


def test_namespace_count_is_bounded_by_the_handle_layout(run):
    assert validate(_with_namespaces(run, 64)).ok
    errs = validate(_with_namespaces(run, 65)).errors
    assert ("65 id namespaces (created tables + p.ids) exceed the 64 that provisional "
            "handles can encode (D11: 6 bits)") in errs


def _run_of(fixture_project, name, overrides=()):
    return resolve_run(load_project(fixture_project(name)), "sample", list(overrides))


def test_chain_depth_two_is_valid_and_bounded(fixture_project):
    assert validate(_run_of(fixture_project, "chain")).ok
    errs = validate(_run_of(fixture_project, "chain", ["budget.max_spawn_depth=1"])).errors
    assert "spawn depth 2 exceeds budget.max_spawn_depth 1 (processes a_main -> b_main)" in errs


def test_creation_cycle_is_an_unbounded_spawn(fixture_project):
    from neorisk_simkit.engine import Res
    run = _run_of(fixture_project, "spawn")
    bad = _with_kernel(run, "pay_main", max=Res(records={"paid": 1}, creates={"pay": 1},
                                                 requests=1))
    assert ("unbounded spawn: owner creation cycle pay -> pay (processes pay_main)"
            in validate(bad).errors)


def test_created_owner_tables_fit_a_creation_message(fixture_project):
    from neorisk_simkit.spec.plan import Column
    from neorisk_simkit.spec.types import f64, i64
    run = _run_of(fixture_project, "spawn")
    plan = run.plan

    def with_pay_cols(cols):
        ts = tuple(dataclasses.replace(t, cols=cols) if t.name == "pay" else t
                   for t in plan.tables)
        return dataclasses.replace(run, plan=dataclasses.replace(plan, tables=ts))

    wide = with_pay_cols(plan.table("pay").cols + tuple(Column(f"x{i}", i64()) for i in range(6)))
    assert "created owner table pay has 8 columns; a creation message carries at most 7" \
        in validate(wide).errors
    floaty = with_pay_cols(plan.table("pay").cols + (Column("rate", f64()),))
    assert ("created owner table pay: column rate is f64; a creation message carries only "
            "int64 values") in validate(floaty).errors


def test_creation_messages_count_toward_the_outbox(fixture_project):
    run = _run_of(fixture_project, "spawn")              # acct_main: requests=3, creates pay 1
    small = dataclasses.replace(run, engine=dataclasses.replace(
        run.engine, force_capacity={"requests": 3}))
    assert ("acct_main: declared maximum of requests 3 plus 1 creation message(s) exceeds the "
            "outbox capacity 3") in validate(small).errors
    fits = dataclasses.replace(run, engine=dataclasses.replace(
        run.engine, force_capacity={"requests": 4}))
    assert not any("creation message(s)" in e for e in validate(fits).errors)


def test_laws_must_resolve_and_count_checker_state(fixture_project):
    """D47: every law path and table resolves; `checker_state` is `max_checker_keys` keys of the
    widest keyed law (`at_most_once` 8 B per key column plus a hash for several, `sum_le` 24 B,
    `resolved` 56 B), reserved only when a keyed law is declared."""
    from neorisk_simkit.spec import law
    from neorisk_simkit.spec.plan import CheckDef

    led = resolve_run(load_project(fixture_project("ledger")), "sample", [])
    assert validate(led).ok                       # row and state laws only: no keys carried
    caps = {c.name: c for c in compute_caps(led)}
    assert caps["checker_state"].hard_bytes == 0
    small = dataclasses.replace(led, budget=dataclasses.replace(led.budget,
                                                                memory_bytes=64 * 2**20))
    check_budget(compute_caps(small), small.budget)
    keyed = dataclasses.replace(led, plan=dataclasses.replace(led.plan, checks=(
        *led.plan.checks, CheckDef("once", law.at_most_once("opened", key="acct_id"), True))))
    caps = {c.name: c for c in compute_caps(keyed)}
    assert caps["checker_state"].hard_bytes == 8 * keyed.budget.max_checker_keys
    with pytest.raises(BudgetError, match="checker_state"):
        check_budget(compute_caps(keyed), small.budget)
    for lw, size in ((law.at_most_once("opened", key=("acct_id", "amount")), 24),
                     (law.sum_le("opened.amount", "entry.amount", by="acct_id"), 24),
                     (law.resolved("opened", by=("entry",), key="acct_id"), 56)):
        wider = dataclasses.replace(keyed, plan=dataclasses.replace(keyed.plan, checks=(
            *keyed.plan.checks, CheckDef("wide", lw, True))))
        caps = {c.name: c for c in compute_caps(wider)}
        assert caps["checker_state"].hard_bytes == size * keyed.budget.max_checker_keys
    checks = (("a", law.never_negative("acct.nope")), ("b", law.total_le("acct.bal", 5)),
              ("c", law.at_most_once("opened", key="nope")), ("d", law.balanced("nope")),
              ("e", law.balanced("entry", side="account")))
    bad = dataclasses.replace(led, plan=dataclasses.replace(
        led.plan, checks=tuple(CheckDef(i, lw, True) for i, lw in checks)))
    assert [e for e in validate(bad).errors if e.startswith("check ")] == [
        "check a: unknown path 'acct.nope'",
        "check b: 'acct.bal' is not an event or posting column",
        "check c: opened has no column nope",
        "check d: unknown event or posting table 'nope'",
        "check e: entry.account must be a cat holding 'debit' and 'credit'"]
