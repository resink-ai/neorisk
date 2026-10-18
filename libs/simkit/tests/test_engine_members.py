"""D74/D75: execution owners emit the acted-for partition's events and create member rows of
its table; base IDs never move."""

import dataclasses

import polars as pl
import pytest
from conftest import FIXTURES, make_run

from neorisk_simkit.engine.errors import LoweringError
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.spec import PackError
from neorisk_simkit.spec.validate import validate


def _run(tmp_path, overrides=()):
    return run_to_dataset(FIXTURES / "crew", "sample", list(overrides),
                          out_dir=tmp_path / "run", threads=2)


def test_member_table_is_the_last_namespace():
    plan = make_run("crew").plan
    assert plan.member_tables == ("user",) and plan.namespaces[-1] == "user"
    assert plan.partition("crew").acts_for == "user"
    assert validate(make_run("crew")).ok


def test_executors_emit_user_events_for_member_rows(tmp_path):
    res = _run(tmp_path)
    users = pl.read_parquet(res.out_dir / "entities" / "user")
    joined = read_events(res.out_dir)["joined"]
    crew_rows = joined.filter(pl.col("partition_id") // (1 << 56) == 3)   # crew is ptype 3
    sizes = pl.read_parquet(res.out_dir / "entities" / "crew")["size"].sum()
    assert crew_rows.height == sizes
    assert users.height == 3 + sizes
    assert set(crew_rows["user_id"]) <= set(users["id"])
    members = users.filter(pl.col("origin") == "member")
    assert members.height == sizes and set(members["id"]) == set(crew_rows["user_id"])


def test_executors_send_the_acted_for_request(tmp_path):
    ev = read_events(_run(tmp_path).out_dir)
    assert ev["asked"].height == 3 + 2


def test_base_ids_do_not_move_with_members(tmp_path):
    a = pl.read_parquet(_run(tmp_path / "a", ["crews=0"]).out_dir / "entities" / "user")
    b = pl.read_parquet(_run(tmp_path / "b").out_dir / "entities" / "user")
    base = b.filter(pl.col("origin") != "member")
    assert a.sort("id").equals(base.sort("id"))


def test_acts_for_needs_an_exposed_owner():
    from neorisk_simkit.spec.pack import Pack
    from neorisk_simkit.spec.types import i32

    p = Pack("x", 1)
    t = p.table("u", key="u_id", mutable=True, cols={"a": i32()})
    p.owner("u", table=t, max_live=1)
    c = p.table("c", key="c_id", mutable=True, cols={"a": i32()})
    with pytest.raises(PackError, match="needs p.expose_owner"):
        p.owner("c", table=c, max_live=1, acts_for="u")


def test_add_member_is_only_for_executors(tmp_path):
    src = (FIXTURES / "crew" / "specs" / "kernels.py").read_text()
    bad = src.replace("out.emit_joined(ctx.t, user_id=ctx.self_id, tier=s.tier)",
                      "out.emit_joined(ctx.t, user_id=out.add_member_user(tier='a'), tier=s.tier)")
    from neorisk_simkit.engine.layout import kernel_layouts
    from neorisk_simkit.engine.lower import lower_module

    plan = make_run("crew").plan
    with pytest.raises(LoweringError, match="unknown out method 'add_member_user'"):
        lower_module(bad, kernel_layouts(plan), {"user_main": "user_main"})


def _with_plan(**changes):
    run = make_run("crew")
    return dataclasses.replace(run, plan=dataclasses.replace(run.plan, **changes))


def test_only_the_acted_for_partition_lends_records_and_boundaries():
    plan = make_run("crew").plan
    parts = tuple(dataclasses.replace(p, acts_for=None) for p in plan.partitions)
    errs = validate(_with_plan(partitions=parts)).errors
    assert any("crew_main reserves records of 'joined' owned by partition 'user'" in e
               for e in errs)
    assert any("crew_main sends boundary 'ask' (ask) from partition 'user', not its own" in e
               for e in errs)


def test_a_member_table_needs_a_population():
    plan = make_run("crew").plan
    pops = tuple(p for p in plan.populations if p.table != "user")
    errs = validate(_with_plan(populations=pops)).errors
    assert any("member table user: an owner acting for its partition needs a population" in e
               for e in errs)
