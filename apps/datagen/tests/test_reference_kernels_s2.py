"""§11: reference models replay the real kernels' decisions and agree with every one."""

import functools
import json
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


def _events(over, tmp_path):
    out = run_to_dataset(EX, "sample", over, out_dir=tmp_path / "run", threads=4).out_dir
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["config"]["run"]["warmup_us"] == 0      # the models need the whole history
    return read_events(out)


@pytest.fixture(scope="module")
def ev(tmp_path_factory):
    return _events(STRESS, tmp_path_factory.mktemp("ref"))


@functools.cache
def _initial(over: tuple[str, ...]):
    """`(on_hand0, sku_group)` keyed by public SKU ID, from the world the run was built with."""
    run = resolve_run(load_project(EX), "sample", list(over))
    w = World.build(run, threads=1)
    items = w.items["inventory"]                         # dense SKU ids in CSR order
    on_hand = w.state["inventory"][0]                    # initial on_hand, CSR order
    group = np.searchsorted(w.offs["inventory"], np.arange(len(items)), side="right") - 1
    pub = public_ids(int(run.seed), "sku", np.asarray(items, np.int64))
    return ({int(p): int(x) for p, x in zip(pub, on_hand, strict=True)},
            {int(p): int(g) for p, g in zip(pub, group, strict=True)})


def _replay_inventory(ev, over, ttl_s):
    on_hand0, sku_group = _initial(tuple(over))
    return replay_inventory(ev, on_hand0, slots=64, sku_group=sku_group,
                            hold_ttl_us=ttl_s * 1_000_000)


def test_inventory_reference(ev):
    assert ev["stock_reserved"].height > 500 and ev["stock_expired"].height > 0
    assert _replay_inventory(ev, STRESS, ttl_s=600) == []


def test_inventory_reference_full_hold_table(tmp_path):
    ev = _events(BUSY, tmp_path)
    reasons = ev["stock_rejected"]["reason"]
    assert (reasons == "busy").sum() > 0 and (reasons == "out_of_stock").sum() > 0
    assert _replay_inventory(ev, BUSY, ttl_s=600) == []


def test_inventory_reference_commit_after_ttl(tmp_path):
    ev = _events(LATE, tmp_path)
    assert ev["stock_commit_late"].height > 0
    assert _replay_inventory(ev, LATE, ttl_s=0) == []


def test_pool_reference(ev):
    assert ev["bonus_rejected"].height > 0
    assert replay_pool(ev, cap=40_000) == []


def test_refund_reference(ev):
    assert ev["refund_replayed"].height > 0 and ev["dispute_opened"].height > 0
    assert replay_refunds(ev, dispute_window_us=90 * int(DAY)) == []   # pack default


def test_refund_reference_short_dispute_window(tmp_path):
    # a 2-day window the 1-day-mean dispute delay often overruns: disputes open only inside it
    ev = _events([*STRESS, "pay.dispute_window_days=2"], tmp_path)
    assert ev["dispute_opened"].height > 0
    assert replay_refunds(ev, dispute_window_us=2 * int(DAY)) == []


def test_references_catch_a_wrong_decision(ev):
    import polars as pl
    flipped = dict(ev)
    g = ev["bonus_granted"]
    flipped["bonus_granted"] = g.with_columns(
        pl.when(pl.int_range(pl.len()) == 0).then(pl.col("remaining_after") + 1)
        .otherwise(pl.col("remaining_after")).alias("remaining_after"))
    assert replay_pool(flipped, cap=40_000)          # a tampered stream is caught
