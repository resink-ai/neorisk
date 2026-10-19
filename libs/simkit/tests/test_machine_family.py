"""Spawn (same owner), join with timeout / duplicates / late policy, repeat with until (§04,
D69, D70; Review Focus 1-2)."""

import json

import polars as pl
import pytest
from conftest import FIXTURES

from neorisk_simkit.engine import EngineError
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

S = 1_000_000


def _run(tmp_path, overrides=()):
    res = run_to_dataset(FIXTURES / "mx_family", "sample", list(overrides),
                         out_dir=tmp_path / "run", threads=2)
    ev = read_events(res.out_dir)
    nests = pl.read_parquet(res.out_dir / "entities" / "nest").select(
        pl.col("id").alias("nest_id"), "brood")
    stats = json.loads((res.out_dir / "run_stats.json").read_text())["machines"]
    return ev, nests, stats


def _fed(ev, nests):
    per = ev["fed"].group_by("nest_id").len()
    return nests.join(per, on="nest_id", how="left").with_columns(pl.col("len").fill_null(0))


def test_join_waits_for_every_child_then_feeds_each(tmp_path):
    ev, nests, st = _run(tmp_path)
    j = _fed(ev, nests)
    assert (j["len"] == j["brood"]).all()
    assert st["mother"]["entries"]["full"] == 4 and st["mother"]["entries"]["timeout"] == 0
    assert st["mother"]["spawned"] == nests["brood"].sum()


def test_zero_children_fire_immediately(tmp_path):
    ev, _nests, st = _run(tmp_path, ["brood_lo=0", "brood_hi=0"])
    assert ev["fed"].height == 0 and ev["called"].height == 0
    assert st["mother"]["entries"]["full"] == 4


def test_duplicates_are_suppressed_and_late_messages_counted(tmp_path):
    ev, _nests, st = _run(tmp_path, ["brood_lo=2", "brood_hi=2"])
    assert ev["fed"].height == 8                         # second calls never double-count
    assert st["mother"]["late"] == 8                     # each chick's second call is late


def test_join_timeout_leaves_and_counts_every_call_late(tmp_path):
    ev, _nests, st = _run(tmp_path, ["brood_lo=1", "brood_hi=1", "wait=4m"])
    assert ev["fed"].height == 0
    assert st["mother"]["entries"]["timeout"] == 4 and st["mother"]["late"] == 8


def test_join_and_timeout_at_one_instant_transition_once(tmp_path):
    _ev, _n, st = _run(tmp_path, ["brood_lo=1", "brood_hi=1", "wait=5m"])   # both at +360 s
    e = st["mother"]["entries"]
    assert e["full"] + e["timeout"] == 4 and e["feeding"] == e["full"]


def test_repeat_stops_at_its_maximum(tmp_path):
    ev, _nests, st = _run(tmp_path, ["brood_lo=2", "brood_hi=2", "max_rounds=1"])
    assert ev["fed"].height == 4 and st["mother"]["entries"]["full"] == 4


def test_spawn_beyond_instances_fails_naming_the_machine(tmp_path):
    with pytest.raises(EngineError, match="mother: no free chick instance"):
        _run(tmp_path, ["brood_lo=2", "brood_hi=2", "chick_slots=1"])


def test_spawn_counts_take_dists_as_parameters():
    from conftest import make_run
    src = make_run("mx_family").plan.machine_sources["nest"]
    assert "ctx.rng.uniform_int(" in src                    # the chick's spawn count (F-18)


def test_spawn_depth_is_bounded_per_machine(tmp_path):
    with pytest.raises(EngineError, match="chick: spawn depth exceeds max_spawn_depth"):
        _run(tmp_path, ["brood_lo=1", "brood_hi=1", "recurse_p=1.0"])


# ---------------------------------------------------------------- generation and validation
def test_depth_limits_are_op_parameters():
    from conftest import make_run
    plan = make_run("mx_family").plan
    cfg = plan.process("mx_nest").config
    assert cfg.x_chick.maxdep == 3                          # declared on the machine
    assert cfg.x_mother.maxdep == 3                         # budget.max_spawn_depth (D72, F-21)
    src = plan.machine_sources["nest"]
    assert "from neorisk_simkit.engine import" in src and "EngineError" in src


def _pack():
    from neorisk_simkit.spec import Pack
    from neorisk_simkit.spec.types import i32, ref
    p = Pack("t", 1)
    t = p.table("acct", key="acct_id", mutable=True, cols={"n": i32()})
    p.owner("acct", table=t, max_live=2)
    p.population(t, n=2, initial=1.0)
    p.event("ping", owner="acct", cols={"acct_id": ref("acct")})
    return p


def _errors(p):
    from neorisk_simkit.machine.spec import build_machines
    return build_machines(p)[1]


def _rep(m, **kw):
    from neorisk_simkit.spec import dist, std
    act = kw.pop("act", std.emit("ping", acct_id=std.actor()))
    return m.state("a", repeat=(dist.constant(s=60), 1.0, act), then="b", **kw).final("b")


def test_repeat_validation():
    from neorisk_simkit.spec import dist, std
    ping = std.emit("ping", acct_id=std.actor())
    cases = [
        (lambda m: m.state("a", branch={"b": (1.0, None, None)}, then="b",
                           until=std.cond.repeats_ge(2)).final("b"),
         "machine m: state 'a': until needs repeat="),
        (lambda m: _rep(m, act=ping.then(ping)),
         "machine m: state 'a': repeat runs one action, not a chain"),
        (lambda m: _rep(m, max_repeats=dist.exp(mean_s=1)),
         ("machine m: state 'a': max_repeats must be an int, std.field, std.col or a "
          "geometric/uniform_int/categorical Dist")),
        (lambda m: _rep(m, max_repeats=2.5),
         ("machine m: state 'a': max_repeats must be an int, std.field, std.col or a "
          "geometric/uniform_int/categorical Dist")),
        (lambda m: _rep(m, max_repeats=std.field("ghost")), "machine m: unknown field 'ghost'"),
    ]
    for build, msg in cases:
        p = _pack()
        build(p.machine("m", owner="acct", initial="a"))
        assert msg in _errors(p), (msg, _errors(p))


def test_max_repeats_and_until_may_read_rep_kids_and_jn():
    from neorisk_simkit.machine.layout import IMPLICIT, READABLE_IMPLICIT
    from neorisk_simkit.spec import dist, std
    assert set(READABLE_IMPLICIT) == {"rep", "kids", "jn"}
    assert set(READABLE_IMPLICIT) <= {f for f, _ in IMPLICIT}
    for f in READABLE_IMPLICIT:
        p = _pack()
        _rep(p.machine("m", owner="acct", initial="a"), max_repeats=std.field(f),
             until=std.cond.ge(std.field(f), 3))
        assert _errors(p) == []
    p = _pack()                                     # other implicit fields stay hidden
    _rep(p.machine("m", owner="acct", initial="a"), max_repeats=std.field("gen"))
    assert "machine m: unknown field 'gen'" in _errors(p)
    p = _pack()                                     # read-only: set_field never names them
    p.machine("m", owner="acct", initial="a").state(
        "a", branch={"b": (1.0, None, std.set_field("jn", 0))}).final("b")
    assert "machine m: unknown field 'jn'" in _errors(p)
    p = _pack()
    _rep(p.machine("m", owner="acct", initial="a"),
         max_repeats=dist.geometric(3, max=5), until=std.cond.ge(std.col("n"), 1))
    assert _errors(p) == []


def _wide_pack(n_outcomes: int, timer: bool):
    """One state branching to `n_outcomes` finals (each a transition), plus a timer."""
    from neorisk_simkit.spec import Pack

    class Mod:
        PACK, SCHEMA_VERSION = "wide", 1

        @staticmethod
        def define(p: Pack, cfg) -> None:
            q = _pack()
            p.__dict__.update(q.__dict__)
            finals = [f"f{j}" for j in range(n_outcomes)]
            m = p.machine("m", owner="acct", start=p.on_created("acct"), initial="a")
            m.state("a", branch={f: (1.0 / n_outcomes, None, None) for f in finals},
                    timer={"f0": "1h"} if timer else None)
            m.final(*finals)

    return Mod


def test_a_machine_has_at_most_256_transitions(tmp_path):
    from neorisk_simkit.spec.pack import PackError
    from neorisk_simkit.spec.plan import build_plan
    plan = build_plan(_wide_pack(256, False), None, tmp_path)   # x holds t << 4 in 12 bits
    assert "mx_tr_m_255" in plan.machine_sources["acct"]
    with pytest.raises(PackError, match="more than 256 transitions"):
        build_plan(_wide_pack(256, True), None, tmp_path)


def test_spawn_depth_must_fit_the_instance_field(tmp_path):
    from neorisk_simkit.spec import Pack, std
    from neorisk_simkit.spec.pack import PackError
    from neorisk_simkit.spec.plan import build_plan

    def mod(depth):
        class Mod:
            PACK, SCHEMA_VERSION = "deep", 1

            @staticmethod
            def define(p: Pack, cfg) -> None:
                p.__dict__.update(_pack().__dict__)
                p.machine("m", owner="acct", start=p.on_created("acct"), initial="a",
                          max_spawn_depth=depth).state(
                    "a", branch={"b": (1.0, None, std.spawn("k"))}).final("b")
                p.machine("k", owner="acct", initial="a").state(
                    "a", branch={"b": (1.0, None, None)}).final("b")
        return Mod

    assert "maxdep" in str(build_plan(mod(127), None, tmp_path).process("mx_acct").config)
    with pytest.raises(PackError, match="max_spawn_depth 128 exceeds 127"):
        build_plan(mod(128), None, tmp_path)
