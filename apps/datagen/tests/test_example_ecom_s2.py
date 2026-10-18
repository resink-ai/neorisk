import json
from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.spec.project import load_project, resolve_run
from neorisk_simkit.spec.validate import validate

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s2"
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=2_000_000"]
SMALL = ["users=3000", "skus=1200", "sku_groups=8", "journey.hot_skus=40",
         "journey.abandon_p=0.1", "run.span=7d", "run.warmup=1d", *POOLS]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return run_to_dataset(EX, "sample", SMALL, out_dir=tmp_path_factory.mktemp("s2") / "run",
                          threads=4)


@pytest.fixture(scope="module")
def ev(run):
    return read_events(run.out_dir)


def _fates(ev):
    return pl.concat([ev[n].select("hold_id", pl.lit(n).alias("fate"))
                      for n in ("stock_committed", "stock_released", "stock_expired")])


def test_project_validates():
    for profile in ("sample", "full", "pool"):
        rep = validate(resolve_run(load_project(EX), profile, []))
        assert rep.ok, (profile, rep.errors)


def test_carts_have_several_lines(ev):
    lines = ev["checkout_started"]["lines"]
    assert lines.max() >= 3 and lines.mean() > 1.2


def test_every_line_is_decided_at_request_time(ev):
    started = ev["checkout_started"].select("checkout_id", "lines",
                                            pl.col("event_time").alias("t"))
    decided = pl.concat([ev["stock_reserved"].select("checkout_id", "event_time"),
                         ev["stock_rejected"].select("checkout_id", "event_time")])
    per = decided.group_by("checkout_id").agg(pl.len().alias("n"),
                                              pl.col("event_time").min().alias("t0"),
                                              pl.col("event_time").max().alias("t1"))
    j = started.join(per, on="checkout_id")
    assert j.height == started.height > 100
    assert (j["n"] == j["lines"].cast(pl.UInt32)).all()
    assert (j["t0"] == j["t"]).all() and (j["t1"] == j["t"]).all()


def test_join_commits_all_or_releases_all(ev):
    holds = ev["stock_reserved"].select("checkout_id", "hold_id").join(
        _fates(ev), on="hold_id", how="inner")
    outcome = pl.concat([
        ev["checkout_succeeded"].select("checkout_id", pl.lit("ok").alias("o")),
        ev["checkout_failed"].select("checkout_id", pl.lit("failed").alias("o")),
        ev["checkout_abandoned"].select("checkout_id", pl.lit("abandoned").alias("o"))])
    j = holds.join(outcome, on="checkout_id")
    want = {"ok": "stock_committed", "failed": "stock_released", "abandoned": "stock_expired"}
    for o, fate in want.items():
        sub = j.filter(pl.col("o") == o)
        assert sub.height > 0, o
        assert (sub["fate"] == fate).all(), (o, sub["fate"].value_counts())


def test_holds_expire_exactly_one_ttl_after_the_reserve(ev):
    r = ev["stock_reserved"].select("hold_id", pl.col("event_time").alias("t0"))
    x = ev["stock_expired"].select("hold_id", "event_time").join(r, on="hold_id")
    assert x.height > 0
    assert ((x["event_time"] - x["t0"]) == timedelta(seconds=600)).all()


def test_two_lines_of_one_cart_can_share_a_shard(ev):
    """Review Focus #2: two lines of one cart reserved in the same inventory group."""
    per = ev["stock_reserved"].group_by("checkout_id", "sku_group").len()
    assert (per["len"] >= 2).any()


def test_the_hot_group_takes_a_share_of_checkouts(run, ev):
    """§10 "one hot SKU group taking 5% of checkouts" (D53, F-02): the shopper's accumulator
    equals the checkouts with a reserve to group 0; the reserve share is information only."""
    m = json.loads((run.out_dir / "manifest.json").read_text())
    started = ev["checkout_started"].select("checkout_id")
    hot_ids = pl.concat([ev["stock_reserved"].select("checkout_id", "sku_group"),
                         ev["stock_rejected"].select("checkout_id", "sku_group")]
                        ).filter(pl.col("sku_group") == 0)["checkout_id"].unique()
    n_hot = started.join(hot_ids.to_frame(), on="checkout_id").height
    assert m["accumulators"]["hot_checkouts"] == n_hot > 0
    assert 0.03 <= n_hot / started.height <= 0.25


def test_laws_hold_and_requests_pair(run):
    m = json.loads((run.out_dir / "manifest.json").read_text())
    for k in ("chk.stock_never_negative", "chk.reserved_never_negative",
              "chk.user_hold_never_negative", "chk.holds_resolved"):
        assert m["laws"][k]["violations"] == 0 and m["laws"][k]["checked"] > 0, k
    pr = m["pairing"]["reserve"]
    assert pr["requests"] == pr["responses"] > 0


def test_a_full_hold_table_rejects_as_busy(tmp_path):
    over = ["users=3000", "skus=600", "sku_groups=2", "journey.session_gap_min_h=0.5",
            "journey.checkout_p=1.0", "journey.abandon_p=1.0", "run.span=1d",
            "run.warmup=0s", *POOLS]
    r = run_to_dataset(EX, "sample", over, out_dir=tmp_path / "busy", threads=2)
    rej = read_events(r.out_dir)["stock_rejected"]
    assert (rej["reason"] == "busy").sum() > 0


def test_a_commit_after_the_ttl_is_late_and_moves_no_stock(tmp_path):
    over = ["users=800", "skus=300", "sku_groups=4", "desk.hold_ttl_s=0", "run.span=3d",
            "run.warmup=0s", *POOLS]
    r = run_to_dataset(EX, "sample", over, out_dir=tmp_path / "late", threads=2)
    ev = read_events(r.out_dir)
    assert ev["stock_committed"].height == 0 and ev["stock_released"].height == 0
    late = ev["stock_commit_late"]
    assert late.height > 0
    assert set(late["checkout_id"]) <= set(ev["checkout_succeeded"]["checkout_id"])


def test_holds_outlive_their_step(run, tmp_path):
    """Review Focus #1: with 1-hour steps, holds reserved in one step are committed or expire
    in the next under their final IDs; counts and the accumulator match the adaptive run."""
    hourly = ["engine.step=1h", "engine.step_min=1h", "engine.step_max=1h", "engine.adapt=false"]
    r = run_to_dataset(EX, "sample", [*SMALL, *hourly], out_dir=tmp_path / "hourly", threads=4)
    a = json.loads((r.out_dir / "manifest.json").read_text())
    b = json.loads((run.out_dir / "manifest.json").read_text())
    assert a["counts"] == b["counts"] and a["accumulators"] == b["accumulators"]
    assert a["laws"].keys() == b["laws"].keys()
    for name, law in a["laws"].items():                    # D47: a state law's `checked` counts
        other = dict(b["laws"][name])                      # live rows per seal, so it depends on
        if law["law"] == "never_negative":                 # the step length
            other["checked"] = law["checked"]
        assert law == other and law["violations"] == 0, name
    ev = read_events(r.out_dir)
    r0 = ev["stock_reserved"].select("hold_id", pl.col("event_time").alias("t0"))
    assert _fates(ev).join(r0, on="hold_id").height == _fates(ev).height > 0
    x = ev["stock_expired"].join(r0, on="hold_id")
    assert (x["event_time"].dt.truncate("1h") != x["t0"].dt.truncate("1h")).sum() > 0
