"""§11: reference models replay the real kernels' decisions and agree with every one."""

import ast
import functools
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from neorisk_simkit.checks.reference import (
    IDEM_SLOTS,
    replay_inventory,
    replay_pool,
    replay_refunds,
)
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.io.seal import public_ids
from neorisk_simkit.spec.project import load_project, resolve_run

pytestmark = pytest.mark.large

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s2"
DAY = 86_400_000_000.0
HOLD_SLOTS = 64                                          # kernels.HOLD_SLOTS of the S2 pack
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


class Events(dict):
    """A run's event tables, plus `pack` (its resolved pack config) and `end_us` (its end)."""


def _events(over, tmp_path):
    out = run_to_dataset(EX, "sample", over, out_dir=tmp_path / "run", threads=4).out_dir
    config = json.loads((out / "manifest.json").read_text())["config"]
    assert config["run"]["warmup_us"] == 0                  # the models need the whole history
    ev = Events(read_events(out))
    ev.pack = config["pack"]
    start = datetime.fromisoformat(config["run"]["start"])
    ev.end_us = int(start.timestamp()) * 1_000_000 + config["run"]["span_us"]
    return ev


_INVENTORY_TABLES = ("stock_reserved", "stock_rejected", "stock_committed", "stock_released",
                     "stock_expired", "stock_commit_late", "restocked")


def _copy(ev):
    out = Events(ev)
    out.pack, out.end_us = ev.pack, ev.end_us
    return out


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


def _replay_inventory(ev, over):
    """The inventory model with the run's own hold TTL and end (resolved config)."""
    on_hand0, sku_group = _initial(tuple(over))
    return replay_inventory(ev, on_hand0, slots=HOLD_SLOTS, sku_group=sku_group,
                            hold_ttl_us=ev.pack["desk"]["hold_ttl_s"] * 1_000_000,
                            end_us=ev.end_us)


def _replay_refunds(ev):
    return replay_refunds(ev, dispute_window_us=ev.pack["pay"]["dispute_window_days"] * int(DAY))


def test_inventory_reference(ev):
    assert ev["stock_reserved"].height > 500 and ev["stock_expired"].height > 0
    assert ev.pack["desk"]["hold_ttl_s"] == 600                          # the pack default
    assert _replay_inventory(ev, STRESS) == []


def test_inventory_reference_full_hold_table(tmp_path):
    ev = _events(BUSY, tmp_path)
    reasons = ev["stock_rejected"]["reason"]
    assert (reasons == "busy").sum() > 0 and (reasons == "out_of_stock").sum() > 0
    assert _replay_inventory(ev, BUSY) == []


def test_inventory_reference_commit_after_ttl(tmp_path):
    ev = _events(LATE, tmp_path)
    assert ev["stock_commit_late"].height > 0 and ev.pack["desk"]["hold_ttl_s"] == 0
    assert _replay_inventory(ev, LATE) == []


def test_pool_reference(ev):
    assert ev["bonus_rejected"].height > 0
    assert replay_pool(ev, cap=ev.pack["pool_cap"]) == []


def test_refund_reference(ev):
    assert ev["refund_replayed"].height > 0 and ev["dispute_opened"].height > 0
    assert ev.pack["pay"]["dispute_window_days"] == 90                    # the pack default
    assert _replay_refunds(ev) == []


def test_refund_reference_short_dispute_window(tmp_path):
    # a 2-day window the 1-day-mean dispute delay often overruns: disputes open only inside it
    ev = _events([*STRESS, "pay.dispute_window_days=2"], tmp_path)
    assert ev["dispute_opened"].height > 0
    assert _replay_refunds(ev) == []


def test_inventory_reference_reports_a_hold_live_past_the_end(ev):
    """A hold whose TTL instant passed before the run's end must have expired; dropping its
    `stock_expired` row (the last row of its group, so no later row trips the overdue check)
    is reported at the end of the stream."""
    import polars as pl
    exp = ev["stock_expired"]
    last = exp.sort("event_time").tail(1)
    group = last["sku_group"][0]
    later = [t for t in _INVENTORY_TABLES if ev[t].height and
             ev[t].filter((pl.col("sku_group") == group)
                          & (pl.col("event_time") > last["event_time"][0])).height]
    assert not later                                     # nothing in its group follows it
    cut = _copy(ev)
    cut["stock_expired"] = exp.filter(pl.col("hold_id") != last["hold_id"][0])
    lines = _replay_inventory(cut, STRESS)
    assert len(lines) == 1 and lines[0].startswith(f"end of stream (sku_group {group}): hold "
                                                   f"{last['hold_id'][0]} live past its TTL")


def test_references_catch_a_wrong_decision(ev):
    import polars as pl
    flipped = _copy(ev)
    g = ev["bonus_granted"]
    flipped["bonus_granted"] = g.with_columns(
        pl.when(pl.int_range(pl.len()) == 0).then(pl.col("remaining_after") + 1)
        .otherwise(pl.col("remaining_after")).alias("remaining_after"))
    assert replay_pool(flipped, cap=ev.pack["pool_cap"])     # a tampered stream is caught


def _bump(ev, table, col, by=1):
    import polars as pl
    out = _copy(ev)
    out[table] = ev[table].with_columns(
        pl.when(pl.int_range(pl.len()) == 0).then(pl.col(col) + by).otherwise(pl.col(col))
        .alias(col))
    return out


def _swap(ev, table, col, a, b):
    import polars as pl
    out = _copy(ev)
    out[table] = ev[table].with_columns(pl.col(col).cast(pl.String).replace({a: b, b: a}))
    return out


def test_inventory_and_refund_references_catch_tampering(ev):
    assert _replay_inventory(_bump(ev, "stock_committed", "on_hand_after"), STRESS)
    rej = _swap(ev, "stock_rejected", "reason", "out_of_stock", "busy")
    assert len(_replay_inventory(rej, STRESS)) == ev["stock_rejected"].height
    assert replay_refunds(_bump(ev, "dispute_opened", "amount"))
    assert replay_refunds(_bump(ev, "refund_settled", "refunded_after"))
    flipped = _swap(ev, "refund_replayed", "result", "requested", "rejected")
    assert len(replay_refunds(flipped)) == ev["refund_replayed"].height


def test_reference_constants_match_the_kernels():
    # a kernel module cannot be imported outside its pack, so read its module-level constants
    # from the parsed source (any spelling of the assignment; other constants are ignored)
    tree = ast.parse((EX / "specs" / "kernels.py").read_text())
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                if isinstance(t, ast.Name) and t.id in ("HOLD_SLOTS", "IDEM_SLOTS"):
                    found[t.id] = ast.literal_eval(node.value)
    assert found == {"HOLD_SLOTS": HOLD_SLOTS, "IDEM_SLOTS": IDEM_SLOTS}
