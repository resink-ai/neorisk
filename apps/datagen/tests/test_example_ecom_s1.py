from pathlib import Path

import polars as pl
import pytest

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.spec.caps import compute_caps, row_bytes
from neorisk_simkit.spec.project import load_project, resolve_run
from neorisk_simkit.spec.validate import validate

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s1"
SMALL = ["users=3000", "skus=1200", "sku_groups=8", "run.span=7d", "run.warmup=1d",
         # engine pools sized for 3k users (the project's are sized for the 2M-user full run)
         "engine.timer_nodes=300_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=200_000"]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return run_to_dataset(EX, "sample", SMALL, out_dir=tmp_path_factory.mktemp("ecom") / "run",
                          threads=4)


@pytest.fixture(scope="module")
def ev(run):
    return read_events(run.out_dir)


def test_project_validates():
    for profile in ("sample", "full"):
        rep = validate(resolve_run(load_project(EX), profile, []))
        assert rep.ok, rep.errors


def test_product_viewed_has_twelve_property_columns(ev):
    assert len(ev["product_viewed"].columns) - 8 == 12


def test_each_checkout_has_at_most_one_outcome(ev):
    outcomes = pl.concat([ev["order_placed"].select("checkout_id"),
                          ev["checkout_failed"].select("checkout_id")])
    assert outcomes.group_by("checkout_id").len()["len"].max() == 1
    started = set(ev["checkout_started"]["checkout_id"])
    resolved = started & set(outcomes["checkout_id"])
    assert len(resolved) >= 0.95 * len(started)


def test_shard_decides_at_request_time(ev):
    # The request is dated at checkout_started and the shard decides at the request's time
    # (D6), so a checkout and its decision share one event_time and are both inside or both
    # outside the export window: every exported checkout has exactly one exported decision,
    # and every exported decision belongs to an exported checkout.
    started = ev["checkout_started"]
    decided = pl.concat([ev["stock_reserved"], ev["stock_rejected"]]).select(
        "checkout_id", pl.col("event_time").alias("decided"))
    assert started.height > 0 and decided["checkout_id"].n_unique() == decided.height
    j = started.join(decided, on="checkout_id")
    assert j.height == started.height == decided.height
    assert (j["event_time"] == j["decided"]).all()


def test_stock_never_negative_and_reservations_resolved(ev):
    for t in ("stock_committed", "restocked"):
        assert ev[t]["on_hand_after"].min() >= 0
    reserved = set(ev["stock_reserved"]["checkout_id"])
    done = set(ev["stock_committed"]["checkout_id"]) | set(ev["stock_released"]["checkout_id"])
    assert len(reserved - done) <= 0.02 * len(reserved)       # only checkouts open at the end


def test_restock_uses_continuations(run, ev):
    assert ev["restocked"].height > 0
    assert run.stats["continuations"] > 0          # 150 SKUs per group: 3 sub-steps of 64


def test_recipe_built_tables_are_exported(run):
    dev = pl.read_parquet(run.out_dir / "entities/device/part-00000.parquet")
    assert dev.height >= 3000 and set(dev["origin"]) == {"static"}
    assert pl.read_parquet(run.out_dir / "entities/sku/part-00000.parquet").height == 1200


def test_rates_are_plausible(ev):
    sessions, checkouts = ev["session_started"].height, ev["checkout_started"].height
    assert 0.01 < checkouts / sessions < 0.30
    oos = ev["checkout_failed"].filter(pl.col("reason") == "out_of_stock").height
    assert oos / checkouts < 0.25


def test_caps_count_recipe_tables_and_refs_csr():
    run = resolve_run(load_project(EX), "sample", SMALL)
    devices = run.plan.populations[0].refs["device"]
    assert devices.max_table_rows("device", 3000) == 3000 * 3          # up to 3 per user
    assert devices.max_csr_entries(3000) == 3001 + 3000 * 4             # offs + own + shared
    read = next(c for c in compute_caps(run) if c.name == "read_inputs").hard_bytes
    plan = run.plan
    expected = (9000 * row_bytes(plan.table("device").cols)
             + 1200 * (row_bytes(plan.table("sku").cols) + 3 * 8)       # stock_target, idx, cumw
             + 8 * devices.max_csr_entries(3000))
    assert read == expected
