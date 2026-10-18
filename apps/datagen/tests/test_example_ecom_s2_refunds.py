import json
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

pytestmark = pytest.mark.large

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
    # a payment opens at most one dispute (`_dispute` needs D_NONE), so joining its close by
    # payment_id pairs each rejection with that one dispute
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


def test_customers_never_recover_more_than_the_capture(ev):
    # review I-1: a dispute covers only what no refund has settled or holds, so settled refunds
    # plus a lost dispute never return more than the capture
    cap = ev["payment_captured"].select("payment_id", pl.col("amount").alias("captured"))
    back = pl.concat([ev["refund_settled"].select("payment_id", "amount"),
                      ev["dispute_lost"].select("payment_id", "amount")])
    tot = back.group_by("payment_id").agg(pl.col("amount").sum()).join(cap, on="payment_id")
    assert ev["dispute_lost"].height > 50
    over = tot.filter(pl.col("amount") > pl.col("captured"))
    assert over.height == 0, over.head()


def test_refunds_after_a_lost_dispute_find_nothing_left(ev):
    lost = ev["dispute_lost"].select("payment_id", pl.col("event_time").alias("tl"))
    after = [ev[n].join(lost, on="payment_id").filter(pl.col("event_time") >= pl.col("tl"))
             for n in ("refund_requested", "refund_rejected")]
    assert after[0].height == 0
    assert after[1].height > 0 and (after[1]["reason"] == "nothing_left").all()


def test_holds_follow_the_remaining_amount(ev):
    """Replay each payment's refund holds in execution order (one payment = one partition)."""
    names = ("payment_captured", "refund_requested", "refund_settled", "refund_failed",
             "refund_rejected", "dispute_opened", "dispute_lost")
    rows = pl.concat([ev[n].select("payment_id", "event_time", "lamport", "event_type",
                                   pl.col("amount") if "amount" in ev[n].columns
                                   else pl.lit(None, pl.Int64).alias("amount"),
                                   pl.col("refunded_after") if n == "refund_settled"
                                   else pl.lit(None, pl.Int64).alias("refunded_after"))
                      for n in names], how="vertical_relaxed")
    rows = rows.with_columns(pl.col("event_type").cast(pl.String)).sort(
        "payment_id", "event_time", "lamport")
    st: dict = {}
    overlapping = 0
    for pid, _t, _l, kind, amt, after in rows.iter_rows():
        p = st.setdefault(pid, {"cap": 0, "ref": 0, "hold": 0, "lost": False})
        left = p["cap"] - p["ref"] - p["hold"]
        if kind == "payment_captured":
            p["cap"] = amt
        elif kind == "refund_requested":
            assert 0 < amt <= left and not p["lost"]
            overlapping += p["hold"] > 0          # a second refund while a hold is unsettled
            p["hold"] += amt
        elif kind == "refund_settled":
            p["hold"] -= amt
            p["ref"] += amt
            assert p["hold"] >= 0 and after == p["ref"] <= p["cap"]
        elif kind == "refund_failed":
            p["hold"] -= amt
            assert p["hold"] >= 0
        elif kind == "dispute_opened":
            assert amt == left > 0                # the remainder no refund has claimed
        elif kind == "dispute_lost":
            p["lost"] = True
    assert overlapping > 0
