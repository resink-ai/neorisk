from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s1"
SMALL = ["users=2000", "skus=200", "sku_groups=4", "run.span=5d", "run.warmup=1d",
         "journey.kyc_start_p=0.5",
         # engine pools sized for 2k users (the project's are sized for the 2M-user full run)
         "engine.timer_nodes=300_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=200_000"]


def _run(tmp_path, *extra):
    r = run_to_dataset(EX, "sample", SMALL + list(extra), out_dir=tmp_path / "run", threads=2)
    return r, read_events(r.out_dir)


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("kyc"))


def test_cross_device_flow(base):
    r, ev = base
    started, done = ev["kyc_started"], ev["kyc_completed"]
    assert started.height > 0 and done.height > 0
    devices = pl.read_parquet(r.out_dir / "entities/device/part-00000.parquet")
    kind = dict(zip(devices["id"], devices["kind"]))
    assert all(kind[d] == "desktop" for d in started["device_id"])
    redeemed = ev["kyc_handoff_redeemed"]
    assert all(kind[d] == "phone" for d in redeemed["device_id"])
    j = done.join(started.select("flow_id", pl.col("session_id").alias("s0")), on="flow_id")
    assert (j["session_id"] == j["s0"]).all()                 # callback to the desktop session
    assert (j["device_id"] != j["scan_device_id"]).all()


def test_change_group_written(base):
    r, ev = base
    hist = pl.read_parquet(sorted((r.out_dir / "history" / "user_kyc").rglob("*.parquet")))
    assert hist.height == ev["kyc_completed"].height
    assert hist.columns[:5] == ["entity_id", "valid_from", "lamport", "partition_id", "seq"]
    assert (hist["kyc_level"] == 1).all()


def test_scan_exactly_at_expiry_counts_as_expired(tmp_path):
    _, ev = _run(tmp_path, "journey.kyc_late_scan_p=1.0", "journey.kyc_duplicate_p=0.0")
    exp, rej = ev["kyc_handoff_expired"], ev["kyc_handoff_rejected"]
    assert ev["kyc_handoff_redeemed"].height == 0 and exp.height > 0
    j = rej.join(exp.select("flow_id", pl.col("event_time").alias("t_exp")), on="flow_id")
    assert (j["reason"] == "expired").all() and (j["event_time"] == j["t_exp"]).all()
    started = ev["kyc_started"].select("flow_id", "expires_at")
    k = exp.join(started, on="flow_id")
    assert (k["event_time"] == k["expires_at"]).all()


def test_second_redemption_is_already_redeemed(tmp_path):
    _, ev = _run(tmp_path, "journey.kyc_duplicate_p=1.0", "journey.kyc_late_scan_p=0.0")
    rej = ev["kyc_handoff_rejected"]
    assert rej.height > 0 and set(rej["reason"]) <= {"already_redeemed", "expired"}
    assert (rej["reason"] == "already_redeemed").sum() > 0
