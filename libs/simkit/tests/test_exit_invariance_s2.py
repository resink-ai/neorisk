"""Spec §10/§12 exit test on the S2 slice: identical logical records across threads, slab
sizes and step lengths, with created payment owners, shard-held handles and a hot shard."""

import itertools
import json
from pathlib import Path

import pytest
from conftest import (
    canonicalize_ids,
    created_namespaces,
    created_owner_codes,
    dataset_tree,
    event_dicts,
)

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

EX2 = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s2"
SMALL2 = ["users=1500", "skus=400", "sku_groups=6", "journey.hot_skus=20",
          "journey.abandon_p=0.2", "referred_share=0.5", "pool_cap=191_000", "hunt.share=0.05",
          "run.span=4d", "run.warmup=1d", "engine.adapt=false",
          "engine.timer_nodes=400_000", "engine.payload_slots=100_000",
          "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
          "budget.max_checker_keys=2_000_000"]
THREADS = (1, 4, 16)
SLABS = ("4MB", "16KB")
STEPS = ("6h", "1d")
ENGINE = {"parallel_min_partitions": 1}
# pool_cap: 191 grants of 1,000 (98 of them exported) run the pool out at 2026-01-03 00:04:22,
# inside the exported span and 4 min after a step boundary of both step lengths, so the race
# for the last unit is exported (measured in all 10 runs, Task 18 fix round 1).


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("inv2")
    out = {}
    for threads, slab, step in itertools.product(THREADS, SLABS, STEPS):
        if threads == 16 and slab == "16KB":
            continue                                       # 10 runs keep CI time bounded
        d = root / f"t{threads}-{slab}-{step}"
        run_to_dataset(EX2, "sample", SMALL2 + [f"engine.slab_bytes={slab!r}",
                                                f"engine.step={step!r}"],
                       out_dir=d, threads=threads, engine_overrides=ENGINE)
        out[(threads, slab, step)] = d
    return out


def test_the_slice_exercises_the_s2_paths(runs):
    d = runs[(1, "4MB", "6h")]
    m = json.loads((d / "manifest.json").read_text())
    c = m["counts"]
    assert c["payment_authorized"] > 200 and c["stock_expired"] > 0
    assert c["bonus_rejected"] > 0 and c["refund_requested"] >= 0
    assert m["entity_counts"]["payment"] > 200


def test_the_pool_runs_out_inside_the_exported_span(runs):
    """The cap edge is exported in every run: claims are granted and rejected after warm-up,
    and the last grant leaves exactly nothing."""
    for run, d in runs.items():
        c = json.loads((d / "manifest.json").read_text())["counts"]
        assert c["bonus_granted"] > 0 and c["bonus_rejected"] > 0, run
        granted = read_events(d)["bonus_granted"].sort("event_time", "lamport")
        assert granted["remaining_after"][-1] == 0, run


@pytest.mark.parametrize("step", STEPS)
def test_threads_and_slabs_give_identical_records(runs, step):
    base = event_dicts(runs[(1, "4MB", step)])
    for (threads, slab, s), d in runs.items():
        if s == step:
            assert event_dicts(d) == base, (threads, slab, step)


def test_step_lengths_give_identical_logical_records(runs):
    """§12 as read by D37: identical logical records as a multiset after ID canonicalization.
    Created IDs and created payments' `partition_id`s are renamed and rows are compared in the
    partition-free order, so only the order among rows tying on (event_time, lamport) across
    partitions is ignored; every value is compared exactly."""
    created = created_namespaces(EX2, SMALL2)
    assert {"payment", "checkout", "hold", "claim"} <= created
    codes = created_owner_codes(EX2, SMALL2, created)
    assert len(codes) == 1                               # `payment`, the created owner type
    for a, b in (((1, "4MB", "6h"), (4, "16KB", "1d")), ((16, "4MB", "6h"), (1, "4MB", "1d"))):
        assert canonicalize_ids(runs[a], created, codes) == \
            canonicalize_ids(runs[b], created, codes), (a, b)


def test_identical_replay_is_byte_identical(runs, tmp_path):
    again = tmp_path / "again"
    run_to_dataset(EX2, "sample", SMALL2 + ["engine.slab_bytes='4MB'", "engine.step='6h'"],
                   out_dir=again, threads=4, engine_overrides=ENGINE)
    assert dataset_tree(runs[(4, "4MB", "6h")]) == dataset_tree(again)


def test_a_hold_ttl_past_15_minutes_runs_clean(tmp_path):
    """Final review I1: `chk.holds_resolved` takes its window from `desk.hold_ttl_s`, so holds
    that expire by a 20-minute TTL are resolved, not violations."""
    d = tmp_path / "ttl"
    run_to_dataset(EX2, "sample", SMALL2 + ["desk.hold_ttl_s=1200", "engine.slab_bytes='4MB'",
                                            "engine.step='6h'"],
                   out_dir=d, threads=4, engine_overrides=ENGINE)
    law = json.loads((d / "manifest.json").read_text())["laws"]["chk.holds_resolved"]
    assert law["violations"] == 0 and law["checked"] > 0
    ev = read_events(d)
    held = ev["stock_expired"].join(ev["stock_reserved"], on="hold_id", suffix="_r")
    assert ((held["event_time"] - held["event_time_r"]).dt.total_seconds() == 1200).all()
    assert held.height > 0
