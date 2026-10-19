"""The overlay contract's engine side (§08, D74-D77, D94, D95; Review Focus 5)."""

import importlib.util
import json
import sys
import textwrap

import numpy as np
import polars as pl
import pytest
from conftest import FIXTURES, canonicalize_ids

from neorisk_simkit import std
from neorisk_simkit.engine.codegen import generate_module
from neorisk_simkit.engine.world import arrival_times
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.io.seal import public_ids
from neorisk_simkit.spec import Overlay, Pack, PackError, dist
from neorisk_simkit.spec.plan import build_plan
from neorisk_simkit.spec.project import ProjectError, load_project, resolve_run
from neorisk_simkit.spec.types import i64, ref
from neorisk_simkit.spec.validate import validate

RING = FIXTURES / "ring"
DAY = 86_400_000_000


def _run(profile="sample", overrides=(), overlays=None):
    return resolve_run(load_project(RING), profile, list(overrides), overlays=overlays)


def _data(tmp_path, overrides=(), overlays=("ring",)):
    res = run_to_dataset(RING, "sample", list(overrides), overlays=list(overlays),
                         out_dir=tmp_path / "run", threads=2)
    return res, read_events(res.out_dir)


@pytest.fixture(scope="module")
def ring(tmp_path_factory):
    """One overlay run and one base run, shared by the dataset tests."""
    root = tmp_path_factory.mktemp("ring")
    return _data(root / "o"), _data(root / "b", overlays=())


def test_overlay_adds_a_cohort_without_touching_the_base():
    base, plan = _run(overlays=[]).plan, _run(overlays=["ring"]).plan
    assert plan.overlays == ("ring",) and plan.partition("gang").acts_for == "user"
    assert {m.name for m in plan.machines} == {"boss", "minion"}
    ev = lambda p: [(e.name, e.cols) for e in p.events if e.group == "events"]
    assert ev(plan) == ev(base)
    assert all(plan.process(p.name).action_id == p.action_id for p in base.processes)
    assert plan.namespaces[:len(base.namespaces)] == base.namespaces
    assert validate(_run(overlays=["ring"])).ok


def test_run_name_and_profile_parameters():
    assert _run(overlays=["ring"]).name == "sample-s7+ring"
    run = _run("gang")
    assert run.overlays == (("ring", {"size": 3, "minions": 2, "arrive_day": 0.0,
                                       "share_device": 0.5, "wait": "2h"}),)
    assert next(c for c in run.plan.cohorts if c.name == "gang").size == 3
    assert next(c for c in _run("gang", ["ring.size=1"]).plan.cohorts).size == 1


def test_an_explicit_overlay_list_replaces_the_profile_list():
    assert _run("gang").plan.overlays == ("ring",)                 # None -> the profile's list
    assert _run("gang", overlays=[]).plan.overlays == ()           # [] replaces it (F-15)
    assert _run("gang", overlays=["ring"]).plan.overlays == ("ring",)


def test_overlay_parameter_errors():
    with pytest.raises(ProjectError, match="overlay ring: unknown parameter 'sizes'"):
        _run(overlays=["ring"], overrides=["ring.sizes=1"])
    with pytest.raises(ProjectError, match="overlay 'nope'"):
        _run(overlays=["nope"])
    with pytest.raises(ProjectError, match="unknown setting 'ring.size'"):
        _run(overlays=[], overrides=["ring.size=1"])              # not enabled: a pack key


def test_overlay_params_never_change_the_source():
    a = _run(overlays=["ring"]).plan.machine_sources
    b = _run(overlays=["ring"], overrides=["ring.minions=3", "ring.share_device=0.2",
                                           "bonus=500"]).plan.machine_sources
    assert a == b                                                  # D77, F-10


def test_spawn_counts_are_bounded_by_the_child_instances_at_build():
    """Task 7 capacities: an int spawn count is a parameter, refused at build above
    min(63, max_instances) of the child (minion: 8)."""
    assert _run(overlays=["ring"], overrides=["ring.minions=8"]).plan.cohorts
    with pytest.raises(PackError, match=r"spawn count of 'minion' must be an int in \[0, 8\]"):
        _run(overlays=["ring"], overrides=["ring.minions=9"])


def test_cohort_machines_read_the_cohorts_refs(ring):
    (res_o, ev), (res_b, _) = ring
    n_base = pl.read_parquet(res_b.out_dir / "entities" / "device").height
    devices = pl.read_parquet(res_o.out_dir / "entities" / "device")
    appended = set(devices["id"].to_list()[n_base:])
    members = pl.read_parquet(res_o.out_dir / "entities" / "user").filter(
        pl.col("origin") == "member").select(pl.col("id").alias("user_id"))
    used = ev["signed_up"].join(members, on="user_id")["device_id"]
    assert used.len() > 0 and set(used.to_list()) <= appended       # F-08


def test_members_emit_base_events_and_labels(ring):
    (res, ev), _ = ring
    d = res.out_dir
    users = pl.read_parquet(d / "entities" / "user")
    members = users.filter(pl.col("origin") == "member")
    assert members.height == 2 * (1 + 2)                     # two gangs: boss + 2 minions
    su = ev["signed_up"].join(members.select(pl.col("id").alias("user_id")), on="user_id")
    assert su.height == members.height
    minions = su.filter(pl.col("invited_by").is_not_null())
    assert minions.height == 4 and set(minions["invited_by"]) <= set(su["user_id"])
    m = json.loads((d / "manifest.json").read_text())
    assert m["label_counts"]["labels_gang"] >= 2 + 4
    labels = pl.read_parquet(sorted((d / "labels" / "labels_gang").rglob("*.parquet")))
    assert set(labels["role"]) == {"boss", "minion"}
    assert (labels["label_available_at"] - labels["event_time"]).dt.total_seconds().min() == 86_400
    assert m["overlays"] == {"ring": {"size": 2, "minions": 2, "arrive_day": 0.0,
                                       "share_device": 0.5, "wait": "2h"}}
    gangs = set(pl.read_parquet(d / "entities" / "gang")["id"])
    assert set(labels["campaign_id"]) <= gangs and set(labels["target_id"]) <= set(members["id"])


def test_cohort_requests_carry_the_executor_as_sender_and_the_member_in_the_payload(ring):
    """Contracts (Tasks 3, 8): a cohort machine's request is stamped with the executing owner's
    id (the gang), and the member it acts for travels in the payload (`who=std.actor()`)."""
    (res, ev), _ = ring
    d, seed = res.out_dir, json.loads((res.out_dir / "manifest.json").read_text())["seed"]
    members = set(pl.read_parquet(d / "entities" / "user").filter(
        pl.col("origin") == "member")["id"])
    gangs = set(pl.read_parquet(d / "entities" / "gang")["id"])
    rows = pl.concat([ev["granted"].select("who", "sender"),
                      ev["refused"].select("who", "sender")])
    by_member = rows.filter(pl.col("who").is_in(list(members)))
    assert by_member.height == 4                              # each minion claims once
    sent_by = set(public_ids(seed, "gang", by_member["sender"].to_numpy()).tolist())
    assert sent_by == gangs                                   # both executors, never a member
    base = rows.filter(~pl.col("who").is_in(list(members)))
    assert base.height == 6
    assert public_ids(seed, "user", base["sender"].to_numpy()).tolist() == base["who"].to_list()


def test_cohort_devices_are_appended_after_base_devices(ring):
    (res_o, _), (res_b, _) = ring
    base = pl.read_parquet(res_b.out_dir / "entities" / "device")
    full = pl.read_parquet(res_o.out_dir / "entities" / "device")
    assert full.height == base.height + 2 * 2
    assert full.head(base.height).equals(base)


def test_a_zero_size_cohort_changes_nothing_in_the_base(tmp_path, ring):
    _, (rb, _) = ring
    ro, _ = _data(tmp_path / "o", ["ring.size=0"])
    # event_id and cause_id compared through the canonical position map (F-01)
    assert canonicalize_ids(ro.out_dir, frozenset()) == canonicalize_ids(rb.out_dir, frozenset())
    m = json.loads((ro.out_dir / "manifest.json").read_text())
    assert m["label_counts"] == {"labels_gang": 0}


def test_a_cohort_arriving_after_the_end_never_acts(tmp_path, ring):
    _, (rb, _) = ring
    ro, _ = _data(tmp_path / "o", ["ring.arrive_day=5.0"])
    assert canonicalize_ids(ro.out_dir, frozenset()) == canonicalize_ids(rb.out_dir, frozenset())
    m = json.loads((ro.out_dir / "manifest.json").read_text())
    assert m["label_counts"] == {"labels_gang": 0}
    assert pl.read_parquet(ro.out_dir / "entities" / "user").filter(
        pl.col("origin") == "member").height == 0


def test_schema_marks_overlay_tables(ring):
    (res, _), (rb, _) = ring
    doc = json.loads((res.out_dir / "schema" / "schema.json").read_text())
    marked = {t["name"]: t["overlay"] for t in doc["tables"] if "overlay" in t}
    assert marked == {"gang": "ring", "labels_gang": "ring"}                  # D95
    base = json.loads((rb.out_dir / "schema" / "schema.json").read_text())
    assert [t for t in doc["tables"] if "overlay" not in t] == base["tables"]


def test_suppress_names_base_processes():
    p = Pack("x", 1)
    t = p.table("user", key="user_id", mutable=True, cols={"n": i64()})
    p.owner("user", table=t, max_live=2)
    p.population(t, n=2, initial=1.0)
    p.expose_owner("user")
    with pytest.raises(PackError, match="suppress names unknown process 'nope'"):
        Overlay(p, "o").cohort("c", table="user", size=1, suppress=["nope"])


def test_overlays_cannot_declare_schema():
    for name in ("event", "table", "process", "request", "message", "shard"):
        assert not hasattr(Overlay, name), name


def test_expose_and_the_base_view():
    p = Pack("x", 1)
    with pytest.raises(PackError, match="expected an @action, a chain or a std.request"):
        p.expose(signup=None)
    p.expose(hello=std.emit("x"))
    with pytest.raises(PackError, match="'hello' is already exposed"):
        p.expose(hello=std.emit("x"))
    p.expose_param("bonus", 7)
    o = Overlay(p, "o")
    assert o.param("bonus") == 7 and o.base.hello == p.exposed["hello"]
    with pytest.raises(AttributeError, match="base pack exposes no 'nope'"):
        o.base.nope                                                    # noqa: B018
    with pytest.raises(PackError, match="exposes no parameter 'x'"):
        o.param("x")


def test_std_label_needs_o_label():
    class Mod:
        PACK, SCHEMA_VERSION = "lab", 1

        @staticmethod
        def define(p: Pack, cfg) -> None:
            t = p.table("user", key="user_id", mutable=True, cols={"n": i64()})
            p.owner("user", table=t, max_live=2)
            p.population(t, n=2, initial=1.0)
            p.expose_owner("user")
            p.event("hi", owner="user", cols={"user_id": ref("user")})

    def apply(o: Overlay) -> None:
        c = o.cohort("crew", table="user", size=1)
        o.machine("m", members=c, initial="a").state(
            "a", branch={"z": (1.0, None, std.emit("hi", user_id=std.actor())
                                .then(std.label("x", "y")))}).final("z")

    with pytest.raises(PackError, match="machine m: std.label needs o.label"):
        build_plan(Mod, None, FIXTURES / "ring" / "specs", overlays=(("o", apply, {}),))


def test_burst_arrivals_fall_in_their_window():
    u = np.linspace(0, 1, 101, endpoint=False)
    start = 10 * DAY
    t = arrival_times(dist.burst(start_day=1.0, span_days=0.5), u, start - DAY, start + 3 * DAY,
                      origin=start)
    assert t.min() >= start + DAY and t.max() < start + DAY + DAY // 2
    with pytest.raises(ValueError, match="burst is an arrival schedule only"):
        dist.encode(dist.burst(start_day=0.0, span_days=1.0))


# ---------------------------------------------------------------- generated module names
_KERNELS = '''
from neorisk_simkit import std
from neorisk_simkit.engine import COMMIT, Res, action


@action(state="{part}", max=Res(records={{"{ev}": 1}}))
def {fn}(ctx, s, m, cmd, out):
    out.emit_{ev}(ctx.t, who=ctx.self_id)
    return COMMIT
'''


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _two_partitions(acts):
    """Machines on partitions `a` and `b`; `acts` maps each to its first part (an @action from
    its own kernels file, or a std helper: no actions file)."""
    class Mod:
        PACK, SCHEMA_VERSION = "two", 1

        @staticmethod
        def define(p: Pack, cfg) -> None:
            for part in ("a", "b"):
                t = p.table(part, key=f"{part}_id", mutable=True, cols={"n": i64()})
                p.owner(part, table=t, max_live=2)
                p.population(t, n=2, initial=1.0)
                p.event(f"{part}_hi", owner=part, cols={"who": ref(part)})
                p.machine(f"m_{part}", owner=part, start=p.on_created(part), initial="x").state(
                    "x", branch={"z": (1.0, None, acts[part])}).final("z")

    return Mod


def test_machine_partitions_in_different_files_share_one_engine_module(tmp_path):
    """Task 6 risk: every machine text defines module constants and `mx_tag`; they are suffixed
    per partition, so two partitions whose actions live in two kernels files (an overlay's own
    file beside the base pack's), or that have no actions file at all, lower into one engine
    module without a name clash."""
    acts = {}
    for part in ("a", "b"):
        f = tmp_path / f"kernels_{part}.py"
        f.write_text(textwrap.dedent(_KERNELS.format(part=part, ev=f"{part}_hi",
                                                     fn=f"hi_{part}")))
        acts[part] = getattr(_load(f, f"t10_kernels_{part}"), f"hi_{part}")
    plan = build_plan(_two_partitions(acts), None, tmp_path)
    assert {p.kernel.module_file for p in plan.processes} == {
        str(tmp_path / "kernels_a.py"), str(tmp_path / "kernels_b.py")}
    for part in ("a", "b"):
        text = plan.machine_sources[part]
        assert f"MX_STALE_{part} = 0" in text and f"def mx_tag_{part}(" in text
    generate_module(plan, checked=False)                        # no clash
    plan = build_plan(_two_partitions({q: std.emit(f"{q}_hi", who=std.actor())
                                       for q in ("a", "b")}), None, tmp_path)
    assert {p.kernel.module_file for p in plan.processes} == {"<machines:a>", "<machines:b>"}
    generate_module(plan, checked=False)


def test_created_owner_depth_falls_back_to_the_budget_for_undeclared_machines(tmp_path):
    """Task 8 review: `mx_<p>.max_spawn_depth` is the smallest machine limit, an undeclared
    machine counting as budget.max_spawn_depth (here 3), not ignored."""
    def pack(depths):
        class Mod:
            PACK, SCHEMA_VERSION = "dep", 1

            @staticmethod
            def define(p: Pack, cfg) -> None:
                t = p.table("a", key="a_id", mutable=True, cols={"n": i64()})
                p.owner("a", table=t, max_live=2)
                p.population(t, n=2, initial=1.0)
                p.event("hi", owner="a", cols={"who": ref("a")})
                for j, d in enumerate(depths):
                    p.machine(f"m{j}", owner="a", start=p.on_created("a") if j == 0 else None,
                              initial="x", max_spawn_depth=d).state(
                        "x", branch={"z": (1.0, None, std.emit("hi", who=std.actor()))}
                    ).final("z")
        return Mod

    def depth(depths):
        return build_plan(pack(depths), None, tmp_path, default_spawn_depth=3).process(
            "mx_a").max_spawn_depth

    assert depth([None, None]) is None                         # the world uses the budget
    assert depth([5, None]) == 3                               # undeclared = budget, not ignored
    assert depth([2, None]) == 2
    assert depth([5, 4]) == 4
