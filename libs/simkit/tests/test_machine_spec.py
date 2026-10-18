"""Machine declarations and their closed-semantics validation (§04, D63-D71)."""

import pytest
from conftest import make_run

from neorisk_simkit.engine import COMMIT, Res, action
from neorisk_simkit.machine import helpers as h
from neorisk_simkit.machine.spec import build_machines
from neorisk_simkit.spec import Pack, PackError, dist, std
from neorisk_simkit.spec.types import i32, ref


def _pack() -> Pack:
    p = Pack("t", 1)
    t = p.table("acct", key="acct_id", mutable=True, cols={"n": i32()})
    p.owner("acct", table=t, max_live=2)
    p.population(t, n=2, initial=1.0)
    p.event("ping", owner="acct", cols={"acct_id": ref("acct")})
    return p


def _errors(p: Pack) -> list[str]:
    return build_machines(p)[1]


def test_mx_basic_builds_into_the_plan():
    plan = make_run("mx_basic").plan
    (m,) = plan.machines
    assert (m.name, m.partition, m.index, m.initial) == ("ship", "parcel", 0, "placed")
    assert [s.name for s in m.states] == ["placed", "expiring", "sent"]
    assert m.finals == ("done", "lost", "expired")
    assert m.code("placed") == 1 and m.code("done") == 4
    placed = m.state("placed")
    assert [o.target for o in placed.branch] == ["sent", "lost"]
    assert placed.branch[1].p is None and placed.timers[0][0] == "expiring"
    (chain,) = [o.chain for o in m.state("sent").branch]
    assert len(chain.parts) == 2 and chain.parts[1].fallback is not None


def test_machines_live_on_owners():
    p = _pack()
    p.shard("desk", key="desk", n=1, items=None, state={})
    with pytest.raises(PackError, match="machines live on owner partitions"):
        p.machine("m", owner="desk", initial="a")


@pytest.mark.parametrize("build, message", [
    (lambda m: m.state("a", branch={"b": (0.5, None, None)}).final("b"),
     ("state 'a': branch probabilities sum to 0.5; give the unpicked mass an explicit "
      "otherwise outcome (p=None)")),
    (lambda m: m.state("a", branch={"b": (None, None, None), "c": (None, None, None)})
     .final("b", "c"), "state 'a': at most one branch outcome may have p=None"),
    (lambda m: m.state("a", branch={"zz": (1.0, None, None)}), "state 'a': unknown target 'zz'"),
    (lambda m: m.state("a").final("b"), "state 'a' has no operation (declare it final)"),
    (lambda m: m.state("a", join={"b": "done"}).final("b"),
     "state 'a': join needs a timer= (its timeout)"),
    (lambda m: m.state("a", request={"b": std.request("x")}).final("b"),
     "state 'a': request needs timeout= and on_reject="),
    (lambda m: m.state("a", repeat=(dist.exp(mean_s=1), 1.0, None), max_repeats=2),
     "state 'a': until/max_repeats need then="),
    (lambda m: m.state("a", join={"b": "x"}, timer={"b": "1h"}, late="sometimes").final("b"),
     "state 'a': late must be 'ignore' or 'count'"),
    (lambda m: m.state("a", branch={"b": (1.0, None, std.emit("nope"))}).final("b"),
     "state 'a': emits unknown event 'nope'"),
    (lambda m: m.state("a", branch={"b": (1.0, None, None)}, spawn={"ghost": (1.0, None, 1)})
     .final("b"), "state 'a': spawns unknown machine 'ghost'"),
])
def test_closed_semantics_errors(build, message):
    p = _pack()
    build(p.machine("m", owner="acct", initial="a", start=p.on_created("acct")))
    assert any(message in e for e in _errors(p)), _errors(p)


def test_initial_must_be_declared():
    p = _pack()
    p.machine("m", owner="acct", initial="nowhere").state(
        "a", branch={"b": (1.0, None, None)}).final("b")
    assert "machine m: initial state 'nowhere' is not declared" in _errors(p)


def test_actions_compose_and_check_their_fields():
    @action(state="acct", max=Res(records={"ping": 1}), fields={"amount": "i64"})
    def pinger(ctx, s, m, cmd, out):
        out.emit_ping(ctx.t, acct_id=m.id)
        return COMMIT

    chain = pinger.then(std.emit("ping", acct_id=std.actor()))
    assert isinstance(chain, h.Chain) and len(chain.parts) == 2
    with pytest.raises(PackError, match="applies to one action"):
        chain.otherwise(std.emit("ping", acct_id=std.actor()))
    p = _pack()
    p.machine("m", owner="acct", initial="a").state(
        "a", branch={"b": (1.0, None, pinger)}).final("b")
    assert "machine m: action pinger needs instance field 'amount' (i64)" in _errors(p)


def test_action_signature_is_checked():
    with pytest.raises(TypeError, match=r"must take \(ctx, s, m, cmd, out\)"):
        @action(state="acct")
        def bad(ctx, s, cmd, out):
            return COMMIT


def _pack2() -> Pack:
    """`_pack()` plus a second owner, a shard and its message/request boundaries."""
    from neorisk_simkit.spec.types import cat
    p = Pack("t", 1)
    t = p.table("acct", key="acct_id", mutable=True, cols={"n": i32(), "tier": cat("lo", "hi")})
    p.owner("acct", table=t, max_live=2)
    p.population(t, n=2, initial=1.0)
    p.event("ping", owner="acct", cols={"acct_id": ref("acct")})
    o = p.table("other", key="other_id", mutable=True, cols={})
    p.owner("other", table=o, max_live=1)
    p.event("pong", owner="other", cols={})
    p.shard("desk", key="desk", n=1, items=None, state={})
    lat = dist.constant(s=1)
    p.message("void", frm="acct", to="desk", payload={}, latency=lat)
    p.message("note", frm="desk", to="acct", payload={}, latency=lat)
    p.request("ask", frm="acct", to="desk", payload={}, responses=("granted",), latency=lat)
    return p


@pytest.mark.parametrize("build, message", [
    (lambda m: m.state("a", branch={"b": (1.0, None, std.emit("pong"))}).final("b"),
     "machine m: state 'a': event 'pong' belongs to partition 'other'"),
    (lambda m: m.state("a", branch={"b": (1.0, None, std.send("note"))}).final("b"),
     "machine m: state 'a': send 'note' is not a message sent by partition 'acct'"),
    (lambda m: m.state("a", request={"b": std.request("ask")}, timeout="1h", on_reject="b")
     .final("b"),
     ("machine m: state 'a': request 'ask' needs release= (a late granted response must be "
      "given back, D67)")),
    (lambda m: m.state("a", request={"b": std.request("ask", release=std.send("note"))},
                       timeout="1h", on_reject="b").final("b"),
     "machine m: state 'a': send 'note' is not a message sent by partition 'acct'"),
    (lambda m: m.state("a", branch={"b": (1.0, None, std.send_parent("done"))}).final("b"),
     "machine m: send_parent('done') but no machine that spawns 'm' joins on 'done'"),
    (lambda m: m.state("a", branch={"b": (1.0, None, std.set_field("ghost", 1))}).final("b"),
     "machine m: unknown field 'ghost'"),
    (lambda m: m.state("a", branch={"b": (1.0, None, std.emit("ping", acct_id=std.field("x")))})
     .final("b"), "machine m: unknown field 'x'"),
    (lambda m: m.state("a", branch={"b": (1.2, None, None), "c": (None, None, None)})
     .final("b", "c"),
     "machine m: state 'a': branch 'b': p must be a float in [0, 1], std.p_by(...) or None"),
    (lambda m: m.state("a", branch={"b": (std.p_by("n", {"lo": 0.5}), None, None),
                                    "c": (None, None, None)}).final("b", "c"),
     "machine m: state 'a': std.p_by needs a category column of 'acct', got 'n'"),
    (lambda m: m.state("a", branch={"b": (std.p_by("tier", {"mid": 0.5}), None, None),
                                    "c": (None, None, None)}).final("b", "c"),
     "machine m: state 'a': std.p_by: 'mid' is not a category of 'tier'"),
    (lambda m: m.state("a", branch={"b": (1.0, None, None)}, timer={"b": "1h"},
                       join={"b": "x"}).final("b"),
     "machine m: state 'a': branch, repeat, join and request exclude each other"),
])
def test_part_and_value_errors(build, message):
    p = _pack2()
    build(p.machine("m", owner="acct", initial="a", fields={"amount": "i64"}))
    assert message in _errors(p), _errors(p)


def test_send_parent_needs_a_joining_spawner():
    p = _pack()
    p.machine("parent", owner="acct", initial="a").state(
        "a", spawn={"kid": (1.0, None, 2)}, join={"b": "done"}, timer={"b": "1h"}).final("b")
    p.machine("kid", owner="acct", initial="a").state(
        "a", branch={"b": (1.0, None, std.send_parent("done"))}).final("b")
    machines, errs = build_machines(p)
    assert errs == [] and [m.index for m in machines] == [0, 1]


def test_machine_declaration_errors():
    p = _pack()
    m = p.machine("m", owner="acct", initial="a", max_instances=65, max_spawn_depth=0,
                  fields={"gen": "i64", "bad": "i64[2]"})
    m.state("a", branch={"a": (1.0, None, None)}).final("a")
    errs = _errors(p)
    for msg in ("machine m: max_instances must be in [1, 64]",
                "machine m: max_spawn_depth must be >= 1",
                "machine m: state 'a' declared twice",
                "machine m: field 'gen' is an implicit instance field (D63)",
                "machine m: field 'bad': 'i64[2]' is not a scalar local type"):
        assert msg in errs, errs
    with pytest.raises(PackError, match="duplicate machine 'm'"):
        p.machine("m", owner="acct", initial="a")
    with pytest.raises(PackError, match="join= takes one"):
        m.state("c", join={"a": "x", "b": "y"})


def test_implicit_field_names_come_from_the_instance_layout():
    from neorisk_simkit.machine.layout import IMPLICIT
    from neorisk_simkit.machine.spec import IMPLICIT_FIELDS
    assert IMPLICIT_FIELDS == tuple(f for f, _ in IMPLICIT) and "mr" in IMPLICIT_FIELDS
    p = _pack()
    p.machine("m", owner="acct", initial="a", fields={"mr": "i16"}).state(
        "a", branch={"b": (1.0, None, None)}).final("b")
    assert "machine m: field 'mr' is an implicit instance field (D63)" in _errors(p)


def test_build_plan_joins_every_machine_error():
    p = _pack()
    p.machine("m", owner="acct", initial="nowhere").state("a").final("b")

    class Mod:
        PACK, SCHEMA_VERSION = "t", 1

        @staticmethod
        def define(q, cfg):
            q.__dict__.update(p.__dict__)

    from pathlib import Path

    from neorisk_simkit.spec.plan import build_plan
    with pytest.raises(PackError) as ei:
        build_plan(Mod, None, Path(__file__).parent / "fixtures" / "mx_basic" / "specs")
    assert str(ei.value).splitlines() == [
        "machine m: initial state 'nowhere' is not declared",
        "machine m: state 'a' has no operation (declare it final)"]
