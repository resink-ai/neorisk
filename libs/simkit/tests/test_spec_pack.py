import pytest

from neorisk_simkit.spec import Pack, PackError
from neorisk_simkit.spec.project import (
    ProjectError,
    load_project,
    parse_duration,
    parse_size,
    resolve_run,
)


def _run(fixture_project, *overrides, profile="sample"):
    return resolve_run(load_project(fixture_project("mini")), profile, list(overrides))


def test_run_spec_from_project(fixture_project):
    run = _run(fixture_project, "users=50", "behavior.take_p=0.5", "engine.step=1h")
    assert run.name == "sample-s7" and run.seed == 7
    assert run.cfg.users == 50 and run.cfg.behavior.take_p == 0.5
    assert run.engine.step_us == 3_600_000_000
    assert run.start_us == 1_772_323_200_000_000          # 2026-03-01T00:00:00Z
    assert run.warmup_us == 6 * 3_600_000_000 and run.span_us == 2 * 86_400_000_000
    assert run.budget.threads == 2 and run.budget.memory_bytes == 2 * 1024**3
    assert run.writer.row_group_rows == 131_072
    assert run.overrides == ("users=50", "behavior.take_p=0.5", "engine.step=1h")


def test_run_prefix_overrides_window(fixture_project):
    run = _run(fixture_project, "run.span=1d", "run.warmup=0s")
    assert run.span_us == 86_400_000_000 and run.warmup_us == 0


def test_seed_override_changes_name(fixture_project):
    run = resolve_run(load_project(fixture_project("mini")), "sample", [], seed=9)
    assert run.name == "sample-s9" and run.seed == 9


def test_unknown_override_and_profile(fixture_project):
    with pytest.raises(ProjectError, match="unknown setting 'userz'"):
        _run(fixture_project, "userz=3")
    with pytest.raises(ProjectError, match="unknown profile 'nope'"):
        _run(fixture_project, profile="nope")
    with pytest.raises(ProjectError, match="expected key=value"):
        _run(fixture_project, "users")


def test_plan_codes_and_lookups(fixture_project):
    plan = _run(fixture_project).plan
    assert plan.pack == "mini" and plan.schema_version == 1 and len(plan.revision) == 7
    assert [t.name for t in plan.tables] == ["item", "user", "note"]
    assert [e.name for e in plan.events] == [
        "user_joined", "ping", "took", "item_taken", "take_failed"]
    assert [e.code for e in plan.events] == [0, 1, 2, 3, 4]
    ping = plan.event("ping")
    assert [c.name for c in ping.cols] == [
        "event_id", "event_type", "event_time", "lamport", "partition_id", "seq", "cause_id",
        "action_id", "user_id", "visit_id", "n", "note_id"]
    assert ping.partition == "user" and ping.kind == "owner"
    assert plan.event("item_taken").kind == "shard"
    take = plan.boundary("take")
    assert take.kind == "request" and take.min_latency_us == 200_000
    assert take.responses == ("ok", "none") and take.frm == "user" and take.to == "bin"
    b = plan.partition("bin")
    assert b.kind == "shard" and b.n == 4 and b.items == "item" and b.key == "bin"
    u = plan.partition("user")
    assert u.kind == "owner" and u.max_live == 200 and u.ptype_code == 1 and b.ptype_code == 2
    assert plan.process("user_main").action_id == 0 and plan.process("bin_desk").action_id == 1
    assert plan.process("user_main").kernel.name == "user_main"
    assert plan.namespaces == ("note", "visit") and plan.ns_code("visit") == 1
    assert plan.table("note").creatable and not plan.table("user").creatable


def test_revision_is_stable(fixture_project):
    assert _run(fixture_project).plan.revision == _run(fixture_project, "users=9").plan.revision


def test_unsupported_vocabulary_names_milestone():
    p = Pack("x", 1)
    with pytest.raises(PackError, match="arrives in M4"):
        p.feature("device_users_24h")


def test_pack_rejects_duplicates_and_unknown_refs():
    p = Pack("x", 1)
    p.table("user", key="user_id", mutable=True, cols={})
    with pytest.raises(PackError, match="duplicate table 'user'"):
        p.table("user", key="user_id", cols={})
    with pytest.raises(PackError, match="unknown partition 'ghost'"):
        p.event("e", owner="ghost", cols={})
    with pytest.raises(PackError, match="exactly one of owner= or shard="):
        p.event("e2", cols={})
    assert p.shard("desk", key="desk", n=1, items=None, state={}) == "desk"
    with pytest.raises(PackError, match="per-item state needs items="):
        p.shard("desk2", key="desk", n=1, items=None, state={"x": "i32[user]"})


def test_make_run_helper_applies_engine_settings():
    from conftest import make_run
    run = make_run("mini", ["users=20"], slab_bytes=4096)
    assert run.cfg.users == 20 and run.engine.slab_bytes == 4096


def test_parse_helpers():
    assert parse_duration("300ms") == 300_000 and parse_duration("90d") == 90 * 86_400_000_000
    assert parse_duration("15m") == 900_000_000
    assert parse_size("8MB") == 8 * 1024**2 and parse_size("16GB") == 16 * 1024**3
    with pytest.raises(ProjectError):
        parse_duration("3 weeks")
