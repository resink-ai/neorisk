"""Machines compile into one generated process per partition (D62); branch, timer, final and
then-chains with a fallback behave as §04 decides."""

import json
import subprocess
import sys

import polars as pl
import pytest
from conftest import FIXTURES, make_run

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

H = 3_600_000_000


def _run(tmp_path, overrides=()):
    return run_to_dataset(FIXTURES / "mx_basic", "sample", list(overrides),
                          out_dir=tmp_path / "run", threads=2)


def test_machines_become_one_generated_process():
    plan = make_run("mx_basic").plan
    mx = plan.process("mx_parcel")
    assert mx.machine_partition == "parcel" and mx.action_id == len(plan.processes) - 1
    assert "def mx_parcel(ctx, s, loc, cmd, out):" in plan.machine_sources["parcel"]
    assert mx.kernel.source.endswith(plan.machine_sources["parcel"])


def _born(res) -> pl.DataFrame:
    return pl.read_parquet(res.out_dir / "entities" / "parcel").select(
        pl.col("id").alias("parcel_id"), pl.col("created_at").cast(pl.Int64).alias("t0"))


def test_earliest_wins_and_stale_timers_drop(tmp_path):
    # sent_p=0.0 forces every parcel onto the 2h "lost" outcome, which the 90m timer beats
    res = _run(tmp_path, ["sent_p=0.0"])
    ev = read_events(res.out_dir)
    assert ev["expired"].height == 6 and ev["lost"].height == 0 and ev["sent"].height == 0
    exp = ev["expired"].join(_born(res), on="parcel_id")
    assert exp.height == 6
    assert (exp["event_time"].cast(pl.Int64) == exp["t0"] + 90 * 60_000_000).all()
    stats = json.loads((res.out_dir / "run_stats.json").read_text())
    assert stats["rejects"]["mx_parcel"] == 6           # each "lost" timer is stale at 2h
    entries = stats["machines"]["ship"]["entries"]
    assert entries["placed"] == entries["expiring"] == entries["expired"] == 6
    assert entries["sent"] == entries["lost"] == 0


def test_sent_beats_the_timer_whose_firing_is_stale(tmp_path):
    res = _run(tmp_path)                                # sent_p=0.5: at least one parcel sent
    ev = read_events(res.out_dir)
    n_sent, n_exp = ev["sent"].height, ev["expired"].height
    assert n_sent >= 1 and n_sent + n_exp == 6 and ev["lost"].height == 0
    sent = ev["sent"].join(_born(res), on="parcel_id")
    assert (sent["event_time"].cast(pl.Int64) == sent["t0"] + H).all()
    stats = json.loads((res.out_dir / "run_stats.json").read_text())
    assert stats["rejects"]["mx_parcel"] == 6           # one stale timer per parcel
    entries = stats["machines"]["ship"]["entries"]
    assert entries["placed"] == 6 and entries["sent"] == n_sent
    assert entries["expiring"] == n_exp and entries["lost"] == 0


def test_then_parts_are_separate_commands_and_the_fallback_runs(tmp_path):
    res = _run(tmp_path, ["sent_p=1.0"])
    ev = read_events(res.out_dir)
    users = pl.read_parquet(res.out_dir / "entities" / "parcel").select(
        pl.col("id").alias("parcel_id"), "weight")
    d = ev["delivered"].join(users, on="parcel_id")
    assert d.height == 6
    heavy = set(d.filter(pl.col("weight") > 5)["parcel_id"])
    assert set(ev["audit_failed"]["parcel_id"]) == heavy
    assert set(ev["audited"]["parcel_id"]) == set(d["parcel_id"]) - heavy
    both = pl.concat([ev["audited"], ev["audit_failed"]]).select(
        "parcel_id", pl.col("lamport").alias("l2"), pl.col("event_time").alias("t2"))
    j = ev["delivered"].join(both, on="parcel_id")
    assert (j["lamport"] < j["l2"]).all() and (j["event_time"] == j["t2"]).all()
    stats = json.loads((res.out_dir / "run_stats.json").read_text())
    assert stats["machines"]["ship"]["rejects"] == len(heavy)


def test_op_parameters_are_config_not_source():
    a = make_run("mx_basic").plan.machine_sources["parcel"]
    b = make_run("mx_basic", ["sent_p=1.0"]).plan.machine_sources["parcel"]
    assert a == b


def test_dump_machines_writes_the_compiled_text(tmp_path):
    out = tmp_path / "dump"
    r = subprocess.run([sys.executable, "-m", "datagen.cli", "validate",
                        str(FIXTURES / "mx_basic"), "--dump-machines", str(out)],
                       check=False, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    plan = make_run("mx_basic").plan
    assert (out / "parcel.py").read_text() == plan.machine_sources["parcel"]


def test_p_by_branches_a_rejected_fallback_and_on_reject(tmp_path):
    res = run_to_dataset(FIXTURES / "mx_branchy", "sample", [], out_dir=tmp_path / "run",
                         threads=2)
    ev = read_events(res.out_dir)
    accts = pl.read_parquet(res.out_dir / "entities" / "acct").select(
        pl.col("id").alias("acct_id"), "tier", "weight")
    gold = accts.filter(pl.col("tier") == "gold")
    heavy = set(gold.filter(pl.col("weight") > 5)["acct_id"])
    light = set(gold["acct_id"]) - heavy
    assert heavy and light and accts.height > gold.height     # seed 7: every path taken
    assert set(ev["picked_gold"]["acct_id"]) == set(gold["acct_id"])        # p_by gold = 1
    assert set(ev["picked_other"]["acct_id"]) == set(accts["acct_id"]) - set(gold["acct_id"])
    assert set(ev["checked"]["acct_id"]) == light
    m = json.loads((res.out_dir / "run_stats.json").read_text())["machines"]["flow"]
    assert m["rejects"] == 2 * len(heavy)            # the part and its rejected fallback (D66)
    assert m["entries"]["failed"] == len(heavy)      # the declared on_reject target
    assert m["entries"]["done"] == len(light)
    assert m["entries"]["other"] == accts.height - gold.height


def _chain_pack(n_parts):
    from neorisk_simkit.spec import Pack, dist, std
    from neorisk_simkit.spec.types import ref

    class Mod:
        PACK, SCHEMA_VERSION = "chain", 1

        @staticmethod
        def define(p: Pack, cfg) -> None:
            t = p.table("acct", key="acct_id", mutable=True, cols={})
            p.owner("acct", table=t, max_live=2)
            p.population(t, n=2, initial=1.0)
            p.event("e", owner="acct", cols={"acct_id": ref("acct")})
            chain = std.emit("e", acct_id=std.actor())
            for _ in range(n_parts - 1):
                chain = chain.then(std.emit("e", acct_id=std.actor()))
            p.machine("m", owner="acct", start=p.on_created("acct"), initial="a").state(
                "a", branch={"b": (1.0, dist.constant(s=1), chain)}).final("b")

    return Mod


def test_then_chains_are_bounded_by_the_continuation_tag(tmp_path):
    from neorisk_simkit.spec.pack import PackError
    from neorisk_simkit.spec.plan import build_plan
    plan = build_plan(_chain_pack(16), None, tmp_path)
    assert "x & 15" in plan.machine_sources["acct"]
    with pytest.raises(PackError, match="then-chain has more than 16 parts"):
        build_plan(_chain_pack(17), None, tmp_path)


def test_fire_dispatch_checks_the_op():
    text = make_run("mx_basic").plan.machine_sources["parcel"]
    assert "if op == 2 and x == 0:" in text and "if op == 1 and x == 1:" in text
    assert "c = ctx.cfg.x_ship" not in text


def test_action_sites_must_be_literals(tmp_path):
    from neorisk_simkit.engine import ActionSpec, Res
    from neorisk_simkit.machine.copy import copy_action
    from neorisk_simkit.spec.pack import PackError

    src = tmp_path / "k.py"
    src.write_text("def a(ctx, s, m, cmd, out):\n"
                   "    n = 3\n"
                   "    x = ctx.rng.uniform(site=n)\n"
                   "    return 0\n"
                   "\n\n"
                   "def b(ctx, s, m, cmd, out):\n"
                   "    x = ctx.rng.uniform(site=3)\n"
                   "    return 0\n")
    md = make_run("mx_basic").plan.machines[0]
    _, text = copy_action(ActionSpec("b", None, str(src), "parcel", Res(), {}), md, 2)
    assert "site=9259" in text                       # 9000 + 128 * 2 + 3
    with pytest.raises(PackError, match="site= must be an int literal"):
        copy_action(ActionSpec("a", None, str(src), "parcel", Res(), {}), md, 0)
