"""Machines compile into one generated process per partition (D62); branch, timer, final and
then-chains with a fallback behave as §04 decides."""

import json
import subprocess
import sys

import polars as pl
from conftest import FIXTURES, make_run

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

H = 3_600_000_000


def _run(tmp_path, overrides=()):
    return run_to_dataset(FIXTURES / "mx_basic", "sample", list(overrides),
                          out_dir=tmp_path / "run", threads=2)


def _us(col: pl.Series) -> list[int]:
    return col.cast(pl.Int64).to_list()


def test_machines_become_one_generated_process():
    plan = make_run("mx_basic").plan
    mx = plan.process("mx_parcel")
    assert mx.machine_partition == "parcel" and mx.action_id == len(plan.processes) - 1
    assert "def mx_parcel(ctx, s, loc, cmd, out):" in plan.machine_sources["parcel"]
    assert mx.kernel.source.endswith(plan.machine_sources["parcel"])


def test_earliest_wins_and_stale_timers_drop(tmp_path):
    res = _run(tmp_path)
    ev = read_events(res.out_dir)
    t0 = _us(ev["sent"]["event_time"])[0] - H if ev["sent"].height else None
    n_sent, n_exp = ev["sent"].height, ev["expired"].height
    assert n_sent + n_exp == 6 and ev["lost"].height == 0       # the 90m timer beats "lost"
    if t0 is not None:
        assert set(_us(ev["expired"]["event_time"])) <= {t0 + 90 * 60_000_000}
    stats = json.loads((res.out_dir / "run_stats.json").read_text())
    assert stats["rejects"]["mx_parcel"] == 6                   # one stale timer per parcel
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
