import json
from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events, read_postings
from neorisk_simkit.spec.project import load_project, resolve_run

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s2"
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=2_000_000"]
SMALL = ["users=3000", "skus=1200", "sku_groups=8", "run.span=7d", "run.warmup=1d",
         "journey.bill_gap.params=[172_800_000_000.0, 0.0, 0.0]",        # bills every ~2 days
         "pay.auth_expiry_s=7200",                                       # expiry races capture
         # captured payments stay live for the 90-day window: ~10k made over 8 days need room
         "payments_live_ratio=5",
         *POOLS]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return run_to_dataset(EX, "sample", SMALL, out_dir=tmp_path_factory.mktemp("pay") / "run",
                          threads=4)


@pytest.fixture(scope="module")
def ev(run):
    return read_events(run.out_dir)


def test_every_payment_starts_where_it_was_created(ev):
    made = pl.concat([ev["checkout_succeeded"].select("payment_id", "event_time"),
                      ev["bill_payment_started"].select("payment_id", "event_time")])
    first = pl.concat([ev["payment_authorized"].select("payment_id", "event_time"),
                       ev["payment_declined"].select("payment_id", "event_time")])
    assert made.height > 1000 and first["payment_id"].n_unique() == first.height
    j = made.join(first, on="payment_id", suffix="_p")
    assert j.height == made.height and (j["event_time"] == j["event_time_p"]).all()


def test_capture_races_expiry(ev):
    auth = ev["payment_authorized"].select("payment_id", pl.col("event_time").alias("t0"))
    cap = ev["payment_captured"].select("payment_id", "event_time").join(auth, on="payment_id")
    exp = ev["payment_expired"].select("payment_id", "event_time").join(auth, on="payment_id")
    assert cap.height > 0 and exp.height > 0
    assert set(cap["payment_id"]).isdisjoint(set(exp["payment_id"]))
    assert ((exp["event_time"] - exp["t0"]) == timedelta(hours=2)).all()
    assert ((cap["event_time"] - cap["t0"]) < timedelta(hours=2)).all()


def test_postings_balance_per_commit_and_fees_accumulate(run, ev):
    led = read_postings(run.out_dir)["ledger"]
    signed = led.with_columns(pl.when(pl.col("side") == "debit").then(pl.col("amount"))
                              .otherwise(-pl.col("amount")).alias("x"))
    assert (signed.group_by("partition_id", "lamport").agg(pl.col("x").sum())["x"] == 0).all()
    m = json.loads((run.out_dir / "manifest.json").read_text())
    assert m["accumulators"]["platform_fees"] == ev["payment_captured"]["fee"].sum()
    pay_events = sum(ev[n].height for n in ("payment_authorized", "payment_declined",
                                            "payment_captured", "payment_expired"))
    assert 2.0 <= m["posting_counts"]["ledger"] / pay_events <= 2.8
    for k in ("chk.postings_balanced", "chk.one_capture"):
        assert m["laws"][k]["violations"] == 0 and m["laws"][k]["checked"] > 0


def test_payment_entities_read_back_with_one_origin_column(run, ev):
    pay = pl.read_parquet(run.out_dir / "entities" / "payment")
    assert pay.columns.count("origin") == 1 and (pay["origin"] == "created").all()
    assert pay.columns[:3] == ["id", "created_at", "origin"]       # the reserved entity head
    made = pl.concat([ev["checkout_succeeded"].select("payment_id", "checkout_id",
                                                      pl.lit("checkout").alias("src")),
                      ev["bill_payment_started"].select("payment_id",
                                                        pl.lit(None, pl.Int64).alias("checkout_id"),
                                                        pl.lit("bill").alias("src"))])
    j = made.join(pay, left_on="payment_id", right_on="id", how="left")
    assert j.height == made.height and (j["source"] == j["src"]).all()
    assert j["checkout_id"].eq_missing(j["checkout_id_right"]).all()


def test_payments_are_their_own_partitions(ev):
    plan = resolve_run(load_project(EX), "sample", []).plan
    code = plan.partition("payment").ptype_code
    pids = ev["payment_authorized"]["partition_id"]
    assert ((pids // (1 << 56)) == code).all() and pids.n_unique() == pids.len()


def test_payments_retire_after_their_window_and_slots_are_reused(tmp_path):
    # F-11: nothing cancels the auth-expiry timer, so a captured payment lives until it fires;
    # a 2 h expiry and a 1-day window keep a payment alive about a day, and bills every ~2 days
    # keep about 450 payments live at once while more than 5,000 are made over 10 days.
    # Retired slots are freed at seal, so a step holds every payment made in it: 12 h steps
    # (D41 would grow this small run's steps to 7 days) keep that under the 1,000 slots
    over = ["users=1000", "skus=300", "sku_groups=4", "run.span=10d", "run.warmup=0s",
            "payments_live_ratio=0.001", "pay.dispute_window_days=1", "pay.auth_expiry_s=7200",
            "journey.bill_gap.params=[172_800_000_000.0, 0.0, 0.0]",
            "engine.step=12h", "engine.step_max=12h", *POOLS]
    r = run_to_dataset(EX, "sample", over, out_dir=tmp_path / "reuse", threads=2)
    ev = read_events(r.out_dir)
    made = ev["checkout_succeeded"].height + ev["bill_payment_started"].height
    assert made > 1_000                     # more payments than the 1,000 live slots (D43)
