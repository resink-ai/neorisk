"""§11: reference models replay the real kernels' decisions and agree with every one."""

from pathlib import Path

import numpy as np
import pytest

from neorisk_simkit.checks.reference import replay_inventory, replay_pool, replay_refunds
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.io.seal import public_ids
from neorisk_simkit.spec.project import load_project, resolve_run

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s2"
DAY = 86_400_000_000.0
POOLS = ["engine.timer_nodes=600_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
         "budget.max_checker_keys=2_000_000"]
# warm-up 0: every decision is exported, so the replay sees the whole history
STRESS = ["users=3000", "skus=600", "sku_groups=4", "run.span=6d", "run.warmup=0s",
          "journey.abandon_p=0.3", "journey.checkout_p=0.9", "journey.session_gap_min_h=6.0",
          "referred_share=0.5", "pool_cap=40_000", "hunt.share=0.05",
          "pay.refund_p=0.6", "pay.duplicate_p=0.5", "pay.dispute_p=0.3",
          f"pay.refund_gap.params=[{0.5 * DAY}, 0.0, 0.0]",
          f"pay.dispute_delay.params=[{1.0 * DAY}, 2.0, 0.0]",
          f"pay.dispute_resolve.params=[{1.0 * DAY}, 2.0, 0.0]", *POOLS]
# forced paths (Review Focus #2), the Task 12 configs: a full hold table, commits after the TTL
BUSY = ["users=3000", "skus=600", "sku_groups=2", "journey.session_gap_min_h=0.5",
        "journey.checkout_p=1.0", "journey.abandon_p=1.0", "run.span=1d", "run.warmup=0s",
        *POOLS]
LATE = ["users=800", "skus=300", "sku_groups=4", "desk.hold_ttl_s=0", "run.span=3d",
        "run.warmup=0s", *POOLS]


@pytest.fixture(scope="module")
def ev(tmp_path_factory):
    r = run_to_dataset(EX, "sample", STRESS, out_dir=tmp_path_factory.mktemp("ref") / "run",
                       threads=4)
    return read_events(r.out_dir)


def _events(over, tmp_path):
    return read_events(run_to_dataset(EX, "sample", over, out_dir=tmp_path / "run",
                                      threads=4).out_dir)


def _on_hand0(over):
    run = resolve_run(load_project(EX), "sample", over)
    w = World.build(run, threads=1)
    items = w.items["inventory"]                         # dense SKU ids in CSR order
    on_hand = w.state["inventory"][0]                    # initial on_hand, CSR order
    pub = public_ids(int(run.seed), "sku", np.asarray(items, np.int64))
    return {int(p): int(x) for p, x in zip(pub, on_hand, strict=True)}


def test_inventory_reference(ev):
    assert ev["stock_reserved"].height > 500 and ev["stock_expired"].height > 0
    assert replay_inventory(ev, _on_hand0(STRESS), slots=64) == []


def test_inventory_reference_full_hold_table(tmp_path):
    ev = _events(BUSY, tmp_path)
    reasons = ev["stock_rejected"]["reason"]
    assert (reasons == "busy").sum() > 0 and (reasons == "out_of_stock").sum() > 0
    assert replay_inventory(ev, _on_hand0(BUSY), slots=64) == []


def test_inventory_reference_commit_after_ttl(tmp_path):
    ev = _events(LATE, tmp_path)
    assert ev["stock_commit_late"].height > 0
    assert replay_inventory(ev, _on_hand0(LATE), slots=64) == []


def test_pool_reference(ev):
    assert ev["bonus_rejected"].height > 0
    assert replay_pool(ev, cap=40_000) == []


def test_refund_reference(ev):
    assert ev["refund_replayed"].height > 0 and ev["dispute_opened"].height > 0
    assert replay_refunds(ev) == []


def test_references_catch_a_wrong_decision(ev):
    import polars as pl
    flipped = dict(ev)
    g = ev["bonus_granted"]
    flipped["bonus_granted"] = g.with_columns(
        pl.when(pl.int_range(pl.len()) == 0).then(pl.col("remaining_after") + 1)
        .otherwise(pl.col("remaining_after")).alias("remaining_after"))
    assert replay_pool(flipped, cap=40_000)          # a tampered stream is caught
