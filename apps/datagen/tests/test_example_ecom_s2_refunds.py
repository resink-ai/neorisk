import json
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s2"
DAY = 86_400_000_000.0
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=2_000_000"]
BUSY = ["users=3000", "skus=1200", "sku_groups=8", "run.span=14d", "run.warmup=0s",
        "pay.refund_p=0.6", "pay.duplicate_p=0.5", "pay.dispute_p=0.3",
        f"pay.refund_gap.params=[{0.5 * DAY}, 0.0, 0.0]",
        f"pay.dispute_delay.params=[{1.0 * DAY}, 2.0, 0.0]",
        f"pay.dispute_resolve.params=[{2.0 * DAY}, 2.0, 0.0]",
        f"pay.refund_settle.params=[{0.25 * DAY}, 0.5, 0.0]", *POOLS]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return run_to_dataset(EX, "sample", BUSY, out_dir=tmp_path_factory.mktemp("ref") / "run",
                          threads=4)


@pytest.fixture(scope="module")
def ev(run):
    return read_events(run.out_dir)


def test_settled_refunds_never_exceed_the_capture(ev):
    cap = ev["payment_captured"].select("payment_id", pl.col("amount").alias("captured"))
    tot = ev["refund_settled"].group_by("payment_id").agg(pl.col("amount").sum())
    j = tot.join(cap, on="payment_id")
    assert j.height > 50 and (j["amount"] <= j["captured"]).all()


def test_refunds_are_rejected_while_a_dispute_is_open(ev):
    rej = ev["refund_rejected"].filter(pl.col("reason") == "dispute_open")
    assert rej.height > 0
    opened = ev["dispute_opened"].select("payment_id", pl.col("event_time").alias("t0"))
    closed = pl.concat([ev["dispute_won"].select("payment_id", "event_time"),
                        ev["dispute_lost"].select("payment_id", "event_time")]).rename(
        {"event_time": "t1"})
    j = rej.join(opened, on="payment_id").join(closed, on="payment_id", how="left")
    assert j.height == rej.height
    assert ((j["event_time"] >= j["t0"]) & (j["t1"].is_null() | (j["event_time"] < j["t1"]))).all()


def test_duplicate_keys_return_the_first_result(ev):
    first = pl.concat([ev["refund_requested"].select("refund_id", pl.lit("requested").alias("f")),
                       ev["refund_rejected"].select("refund_id", pl.lit("rejected").alias("f"))])
    rep = ev["refund_replayed"].join(first, on="refund_id")
    assert rep.height > 0 and (rep["result"].cast(pl.String) == rep["f"]).all()
    for t in ("refund_settled", "refund_failed"):          # replays change nothing
        assert ev[t]["refund_id"].n_unique() == ev[t].height


def test_each_refund_settles_or_fails_once(ev):
    done = pl.concat([ev["refund_settled"].select("refund_id"),
                      ev["refund_failed"].select("refund_id")])
    assert done["refund_id"].n_unique() == done.height > 0
    assert set(done["refund_id"]) <= set(ev["refund_requested"]["refund_id"])


def test_disputes_resolve_once_for_the_disputed_amount(ev):
    o = ev["dispute_opened"].select("payment_id", pl.col("amount").alias("a"))
    r = pl.concat([ev["dispute_won"].select("payment_id", "amount"),
                   ev["dispute_lost"].select("payment_id", "amount")])
    assert r["payment_id"].n_unique() == r.height > 0
    j = r.join(o, on="payment_id")
    assert (j["amount"] == j["a"]).all()


def test_payment_laws_hold(run):
    laws = json.loads((run.out_dir / "manifest.json").read_text())["laws"]
    for k in ("chk.refunds_le_captured", "chk.refund_settles_once", "chk.postings_balanced"):
        assert laws[k]["violations"] == 0 and laws[k]["checked"] > 0, k
