"""Spec §10/§12 exit test on the S2 slice: identical logical records across threads, slab
sizes and step lengths, with created payment owners, shard-held handles and a hot shard.

Every emitted record is compared: events, postings, entity tables and the manifest's totals
(accumulators, counts, laws). Threads and slabs must give byte-identical datasets; step
lengths give identical records after ID canonicalization (D37)."""

import itertools
import json
from collections import Counter
from pathlib import Path

import pytest
from conftest import (
    _plan_of,
    canonicalize_ids,
    created_namespaces,
    created_owner_codes,
    dataset_tree,
)

from neorisk_simkit.checks.laws import resolve_path
from neorisk_simkit.engine.codegen import NEED_SWAP
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

EX2 = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s2"
DAY = 86_400_000_000.0
SMALL2 = ["users=1500", "skus=400", "sku_groups=6", "journey.hot_skus=20",
          "journey.abandon_p=0.2", "referred_share=0.5", "pool_cap=191_000", "hunt.share=0.05",
          "run.span=4d", "run.warmup=1d", "engine.adapt=false",
          "engine.timer_nodes=400_000", "engine.payload_slots=100_000",
          "engine.max_messages_per_step=300_000", "budget.max_admissions_per_step=50_000",
          "budget.max_checker_keys=2_000_000"]
# refunds and disputes are rare at the pack's rates (SMALL2 alone: 5 refunds, no dispute), so
# the matrix forces them; every payment path then runs under every axis
PAY = ["pay.refund_p=0.4", "pay.duplicate_p=0.3", "pay.dispute_p=0.2",
       f"pay.refund_gap.params=[{0.5 * DAY}, 0.0, 0.0]",
       f"pay.dispute_delay.params=[{0.5 * DAY}, 2.0, 0.0]",
       f"pay.dispute_resolve.params=[{0.5 * DAY}, 2.0, 0.0]"]
THREADS = (1, 4, 16)
SLABS = ("4MB", "16KB")             # 16KB forces slab swaps (record flushes, outbox move-asides)
STEPS = ("6h", "1d")
ENGINE = {"parallel_min_partitions": 1}     # every phase goes through the thread pool
COMPILED = (4, "4MB", "6h", "compiled")     # the project's parallel_min_partitions (2,048):
                                            # rounds and admissions run in compiled code
# pool_cap: 191 grants of 1,000 run the pool out inside the exported span, so the move from
# granting to rejecting is exported (Task 18 fix round 1; asserted in every run below).


def _run(out_dir: Path, threads: int, slab: str, step: str, engine) -> dict:
    """Run the slice; return what the execution did: the workers that ran partitions, the
    slab-full swaps (record flushes and outbox move-asides) and the run stats."""
    workers: set[int] = set()
    swaps: Counter[str] = Counter()
    run_slots, handle_status = World.run_slots, World.handle_status

    def spy_run_slots(self, worker, slots, limit_t, *, owners):
        if len(slots):
            workers.add(worker)
        return run_slots(self, worker, slots, limit_t, owners=owners)

    def spy_handle_status(self, worker, status):
        if status == NEED_SWAP:
            slab_ = self.slabs[worker]
            m = int(slab_.miss[0])
            swaps["outbox" if m >= 0 and slab_.resources[m] == "requests" else "flush"] += 1
        return handle_status(self, worker, status)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(World, "run_slots", spy_run_slots)
        mp.setattr(World, "handle_status", spy_handle_status)
        run_to_dataset(EX2, "sample", SMALL2 + PAY + [f"engine.slab_bytes={slab!r}",
                                                      f"engine.step={step!r}"],
                       out_dir=out_dir, threads=threads, engine_overrides=engine)
    stats = json.loads((out_dir / "run_stats.json").read_text())
    return {"workers": workers, "swaps": swaps, "stats": stats}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("inv2")
    out, probes = {}, {}
    for threads, slab, step in itertools.product(THREADS, SLABS, STEPS):
        d = root / f"t{threads}-{slab}-{step}"
        probes[(threads, slab, step)] = _run(d, threads, slab, step, ENGINE)
        out[(threads, slab, step)] = d
    d = root / "compiled"
    probes[COMPILED] = _run(d, *COMPILED[:3], None)
    out[COMPILED] = d
    return out, probes


def _manifest(d: Path) -> dict:
    return json.loads((d / "manifest.json").read_text())


def _records(d: Path) -> dict[str, bytes]:
    """Every data file (events, postings, entities, `_index`, schema), byte for byte: all but
    the manifest (it records the thread and slab settings) and run_stats.json."""
    return {k: v for k, v in dataset_tree(d).items() if k != "manifest.json"}


def _totals(d: Path, state_laws: frozenset[str] = frozenset()) -> dict:
    """The manifest's logical totals; `checked` of the state laws is left out (D47: a state law
    checks live partitions at every exported seal, so its count depends on step length)."""
    m = _manifest(d)
    laws = {k: {f: v for f, v in law.items() if not (f == "checked" and k in state_laws)}
            for k, law in m["laws"].items()}
    keys = ("counts", "posting_counts", "entity_counts", "history_counts", "accumulators",
            "pairing", "late_messages")
    return {**{k: m[k] for k in keys}, "laws": laws}


def test_the_slice_exercises_the_s2_paths(runs):
    dirs, _ = runs
    for run, d in dirs.items():
        m = _manifest(d)
        c = m["counts"]
        assert c["payment_authorized"] > 200 and c["stock_expired"] > 0, run
        assert c["bonus_rejected"] > 0 and c["refund_requested"] > 20, run
        assert c["refund_replayed"] > 0 and c["refund_settled"] > 0, run
        assert c["dispute_opened"] > 0 and c["dispute_won"] + c["dispute_lost"] > 0, run
        assert m["entity_counts"]["payment"] > 200 and m["posting_counts"]["ledger"] > 0, run
        assert all(v > 0 for v in m["accumulators"].values()), run


def test_the_pool_runs_out_inside_the_exported_span(runs):
    """The cap edge is exported in every run: claims are granted and rejected after warm-up,
    and the last grant leaves exactly nothing."""
    dirs, _ = runs
    for run, d in dirs.items():
        c = _manifest(d)["counts"]
        assert c["bonus_granted"] > 0 and c["bonus_rejected"] > 0, run
        granted = read_events(d)["bonus_granted"].sort("event_time", "lamport")
        assert granted["remaining_after"][-1] == 0, run


def test_each_axis_varies_the_execution(runs):
    """Guard against a vacuous pass (Task 18 M1): more threads really split the work, a 16KB
    slab really swaps, the step lengths really move the step boundaries, and the compiled run
    really runs rounds and admissions in compiled code (final review M5)."""
    _, probes = runs
    for key, p in probes.items():
        threads, slab, step = key[:3]
        st = p["stats"]
        assert st["threads"] == threads, key
        assert st["steps"] == {"6h": 20, "1d": 5}[step], key
        if key == COMPILED:
            assert st["compiled_rounds_total"] > 0 and st["compiled_admissions_total"] > 0, st
            continue
        assert p["workers"] == set(range(threads)), key
        assert st["compiled_rounds_total"] == st["compiled_admissions_total"] == 0, key
        if slab == "16KB":
            assert p["swaps"]["flush"] >= 10, (key, p["swaps"])
        else:
            assert not p["swaps"], (key, p["swaps"])                  # 4MB never fills


@pytest.mark.parametrize("step", STEPS)
def test_threads_and_slabs_give_identical_records(runs, step):
    """Byte-identical datasets (events, postings, entities, the step index) and equal totals
    across 1, 4 and 16 threads, both slab sizes, and Python vs compiled rounds."""
    dirs, _ = runs
    base = dirs[(1, "4MB", step)]
    records, totals = _records(base), _totals(base)
    assert any(k.startswith("postings/") for k in records)
    assert any(k.startswith("entities/payment/") for k in records)
    for key, d in dirs.items():
        if key[2] == step:
            assert _records(d) == records, key
            assert _totals(d) == totals, key


def test_step_lengths_give_identical_logical_records(runs):
    """§12 as read by D37: identical logical records as a multiset after ID canonicalization,
    for events, postings and entity tables alike. Created IDs and created payments'
    `partition_id`s are renamed and rows are compared in the partition-free order, so only the
    order among rows tying on (event_time, lamport) across partitions is ignored; every value
    is compared exactly. The manifest's totals are equal too (state-law `checked` aside)."""
    dirs, _ = runs
    created = created_namespaces(EX2, SMALL2)
    assert {"payment", "checkout", "hold", "claim"} <= created
    codes = created_owner_codes(EX2, SMALL2, created)
    assert len(codes) == 1                               # `payment`, the created owner type
    plan = _plan_of(EX2, SMALL2)
    state_laws = frozenset(c.id for c in plan.checks if c.law.kind == "never_negative"
                           and resolve_path(plan, c.law.arg("path"))[0] != "event")
    assert state_laws
    for a, b in (((1, "4MB", "6h"), (4, "16KB", "1d")), ((16, "4MB", "6h"), (1, "4MB", "1d")),
                 ((16, "16KB", "6h"), (16, "16KB", "1d"))):
        ra = canonicalize_ids(dirs[a], created, codes, everything=True)
        rb = canonicalize_ids(dirs[b], created, codes, everything=True)
        assert ra["ledger"] and ra["entities/payment"]
        assert ra == rb, (a, b)
        assert _totals(dirs[a], state_laws) == _totals(dirs[b], state_laws), (a, b)


def test_identical_replay_is_byte_identical(runs, tmp_path):
    dirs, _ = runs
    again = tmp_path / "again"
    run_to_dataset(EX2, "sample", SMALL2 + PAY + ["engine.slab_bytes='4MB'", "engine.step='6h'"],
                   out_dir=again, threads=4, engine_overrides=ENGINE)
    assert dataset_tree(dirs[(4, "4MB", "6h")]) == dataset_tree(again)


def test_a_hold_ttl_past_15_minutes_runs_clean(tmp_path):
    """Final review I1: `chk.holds_resolved` takes its window from `desk.hold_ttl_s`, so holds
    that expire by a 20-minute TTL are resolved, not violations."""
    d = tmp_path / "ttl"
    run_to_dataset(EX2, "sample", SMALL2 + ["desk.hold_ttl_s=1200", "engine.slab_bytes='4MB'",
                                            "engine.step='6h'"],
                   out_dir=d, threads=4, engine_overrides=ENGINE)
    law = _manifest(d)["laws"]["chk.holds_resolved"]
    assert law["violations"] == 0 and law["checked"] > 0
    ev = read_events(d)
    held = ev["stock_expired"].join(ev["stock_reserved"], on="hold_id", suffix="_r")
    assert held.height > 0
    assert ((held["event_time"] - held["event_time_r"]).dt.total_seconds() == 1200).all()
