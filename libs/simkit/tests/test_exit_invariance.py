"""Spec §10/§12 exit test: identical logical records across 1, 4 and 16 threads, two slab sizes
and two step lengths; identical replay is byte-identical. The `creators` fixture adds owners that
create owners (which draw randomness and tie in canonical order) across step boundaries."""

import itertools
import json
from collections import Counter
from pathlib import Path

import polars as pl
import pytest
from conftest import (
    canonicalize_ids,
    created_namespaces,
    created_owner_codes,
    dataset_tree,
    event_dicts,
)

from neorisk_simkit.engine.codegen import NEED_SWAP
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s1"
CREATORS = Path(__file__).resolve().parent / "fixtures" / "creators"
SMALL = ["users=1500", "skus=300", "sku_groups=8", "run.span=4d", "run.warmup=1d",
         "journey.kyc_start_p=0.3", "engine.adapt=false",
         # engine pools sized for 1.5k users (the project's are sized for the 2M-user full run)
         "engine.timer_nodes=300_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=200_000"]
THREADS = (1, 4, 16)
SLABS = ("8MB", "16KB")             # 16KB forces constant slab swaps (RETRY path)
STEPS = ("6h", "1d")
ENGINE = {"parallel_min_partitions": 1}     # every phase goes through the thread pool


def _run(out_dir: Path, threads: int, slab: str, step: str) -> dict:
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
        run_to_dataset(EX, "sample", SMALL + [f"engine.slab_bytes={slab!r}",
                                              f"engine.step={step!r}"],
                       out_dir=out_dir, threads=threads, engine_overrides=ENGINE)
    stats = json.loads((out_dir / "run_stats.json").read_text())
    return {"workers": workers, "swaps": swaps, "stats": stats}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("inv")
    out, probes = {}, {}
    for threads, slab, step in itertools.product(THREADS, SLABS, STEPS):
        d = root / f"t{threads}-{slab}-{step}"
        probes[(threads, slab, step)] = _run(d, threads, slab, step)
        out[(threads, slab, step)] = d
    return out, probes


def test_each_axis_varies_the_execution(runs):
    """Guard against a vacuous pass: more threads really split the work, a 16KB slab really
    swaps (record flushes and outbox move-asides) and the step lengths really move the step
    boundaries."""
    _, probes = runs
    for (threads, slab, step), p in probes.items():
        assert p["workers"] == set(range(threads)), (threads, slab, step)
        assert p["stats"]["threads"] == threads
        assert p["stats"]["steps"] == {"6h": 20, "1d": 5}[step], (threads, slab, step)
        if slab == "16KB":
            assert p["swaps"]["flush"] >= 10, (threads, step, p["swaps"])
            if threads == 1:                  # one worker's outbox overflows mid-phase
                assert p["swaps"]["outbox"] > 0, (step, p["swaps"])
        else:
            assert not p["swaps"], (threads, step, p["swaps"])   # 8MB never fills


@pytest.mark.parametrize("step", STEPS)
def test_threads_and_slabs_give_identical_records(runs, step):
    dirs, _ = runs
    base = event_dicts(dirs[(1, "8MB", step)])
    assert sum(len(v) for v in base.values()) > 10_000
    for threads, slab in itertools.product(THREADS, SLABS):
        assert event_dicts(dirs[(threads, slab, step)]) == base, (threads, slab, step)


def test_step_lengths_give_identical_logical_records(runs):
    dirs, _ = runs
    created = created_namespaces(EX, SMALL)
    assert {"session", "checkout"} <= created and created.isdisjoint({"user", "sku", "device"})
    assert canonicalize_ids(dirs[(1, "8MB", "6h")], created) == \
        canonicalize_ids(dirs[(4, "16KB", "1d")], created)


def test_identical_replay_is_byte_identical(runs, tmp_path):
    dirs, _ = runs
    again = tmp_path / "again"
    run_to_dataset(EX, "sample", SMALL + ["engine.slab_bytes='8MB'", "engine.step='6h'"],
                   out_dir=again, threads=4, engine_overrides=ENGINE)
    assert dataset_tree(dirs[(4, "8MB", "6h")]) == dataset_tree(again)


# ---------------------------------------------------------------------------- created owners
CREATOR_RUNS = ((1, "30m"), (1, "6h"), (4, "6h"), (1, "1d"))


@pytest.fixture(scope="module")
def creator_runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("creators")
    out = {}
    for threads, step in CREATOR_RUNS:
        d = root / f"t{threads}-{step}"
        run_to_dataset(CREATORS, "sample", [f"engine.step={step!r}"], out_dir=d,
                       threads=threads, engine_overrides=ENGINE)
        out[(threads, step)] = d
    return out


def test_creators_fixture_crosses_steps_and_ties(creator_runs):
    """Guard against a vacuous pass: the step lengths really split one account's creations
    over different steps, payments draw randomness, and payments of different accounts tie
    at an equal (event_time, lamport)."""
    steps = {s: json.loads((creator_runs[(1, s)] / "run_stats.json").read_text())["steps"]
             for s in ("30m", "6h", "1d")}
    assert steps == {"30m": 48, "6h": 4, "1d": 1}
    ev = read_events(creator_runs[(1, "6h")])
    spawned, paid, ticked = ev["spawned"], ev["paid"], ev["ticked"]
    assert spawned.height == paid.height == ticked.height == 6 * 4
    per_acct = spawned.group_by("acct_id").agg(pl.col("event_time").n_unique().alias("n"))
    assert (per_acct["n"] == 3).all()               # three separate creating commits each
    assert paid["draw"].n_unique() == paid.height    # every payment draws its own value
    ties = ticked.group_by("event_time", "lamport").agg(pl.col("acct_id").n_unique().alias("a"))
    assert (ties["a"] > 1).any()                     # cross-account canonical-order ties
    refunded = ev["refunded"]                        # owners created by created owners
    assert refunded.height == 2 * 2 * 6 and refunded["draw"].n_unique() == refunded.height
    first = refunded.filter(pl.col("phase") == 0).join(paid, on="pay_id")
    assert (first["event_time"] == first["event_time_right"]).all()
    ties = refunded.group_by("event_time", "lamport").len()
    assert (ties["len"] > 1).any()


def test_created_owners_identical_across_threads(creator_runs):
    assert event_dicts(creator_runs[(1, "6h")]) == event_dicts(creator_runs[(4, "6h")])


def test_created_owners_identical_across_step_lengths(creator_runs):
    """A created owner's draws and records do not depend on where the step boundaries fall
    (C1 of the S1 final review). Its dense index, hence `partition_id`, legitimately does
    (spec §12, D13), so the comparison renames them and drops `partition_id` from the order."""
    created = created_namespaces(CREATORS, [])
    assert created == {"pay", "refund"}
    codes = created_owner_codes(CREATORS, [], created)
    base = canonicalize_ids(creator_runs[(1, "1d")], created, codes)
    for step in ("30m", "6h"):
        assert canonicalize_ids(creator_runs[(1, step)], created, codes) == base, step


def test_created_dense_indices_follow_creator_partition_order(creator_runs):
    """Spec §12: rows created in one step get dense indices by creator `partition_id`, then
    local ordinal, whatever their creation times. In the one-step run, higher accounts create
    their pair of payments earlier, yet each payment's dense index (its `partition_id` serial)
    ranks by the creating account first (Codex regression: p0 creating at t=20 and p1 at t=10
    in one step gives [0, 1])."""
    ev = read_events(creator_runs[(1, "1d")])
    sp = ev["spawned"].select(pl.col("partition_id").alias("creator"), "seq", "pay_id",
                              pl.col("event_time").alias("created_at"))
    paid = ev["paid"].select("pay_id", (pl.col("partition_id") & ((1 << 56) - 1)).alias("dense"))
    rows = sp.join(paid, on="pay_id").sort("dense")
    assert rows.height == 6 * 4
    assert rows["dense"].to_list() == list(range(rows.height))
    assert rows.select("creator", "seq").equals(rows.select("creator", "seq").sort("creator",
                                                                                  "seq"))
    # non-vacuous: some account with a lower partition_id created a payment later than a
    # higher account did
    t = rows["created_at"].to_list()
    assert any(t[i] > t[j] for i in range(len(t)) for j in range(i + 1, len(t)))


# ---------------------------------------------------------------------------- D61
RELAY = Path(__file__).resolve().parent / "fixtures" / "relay"


@pytest.fixture(scope="module")
def relay_runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("relay")
    out = {}
    for step in ("30m", "6h", "1d"):
        d = root / step
        run_to_dataset(RELAY, "sample", [f"engine.step={step!r}"], out_dir=d, threads=1)
        out[step] = d
    return out


def test_tied_requests_from_new_owners_route_step_invariantly(relay_runs):
    """A pay asks at 01:00 while provisional (6h, 1d) or dense (30m); its requests tie with
    the peers' at (time, prio, cause) and must reach the desk in the same order."""
    orders = {}
    for step, d in relay_runs.items():
        asked = read_events(d)["asked"].sort("event_time", "lamport", "partition_id", "seq")
        assert asked.height == 4 and asked["event_time"].dt.hour().to_list() == [1] * 4, step
        orders[step] = asked["v"].to_list()
    assert orders["30m"] == orders["6h"] == orders["1d"] == [0, 0, 1, 1]   # pay type first


LATECOMER = Path(__file__).resolve().parent / "fixtures" / "latecomer"


@pytest.fixture(scope="module")
def latecomer_runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("latecomer")
    out = {}
    for step in ("1h", "6h", "1d"):
        d = root / step
        run_to_dataset(LATECOMER, "sample", [f"engine.step={step!r}"], out_dir=d, threads=1)
        out[step] = d
    return out


def test_tied_requests_arriving_in_different_rounds_run_step_invariantly(latecomer_runs):
    """Population owners only: with 6h or 1d steps the peer's 01:00 ask reaches the desk a
    round before the asker's tied one; the desk must still run them in sender-key order."""
    orders = {}
    for step, d in latecomer_runs.items():
        asked = read_events(d)["asked"].sort("event_time", "lamport", "partition_id", "seq")
        assert asked.height == 2 and asked["event_time"].dt.hour().to_list() == [1] * 2, step
        orders[step] = asked["v"].to_list()
    assert orders["1h"] == orders["6h"] == orders["1d"] == [0, 1]   # asker type first


MIXED = Path(__file__).resolve().parent / "fixtures" / "mixed"


@pytest.fixture(scope="module")
def mixed_runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("mixed")
    out = {}
    for step, threads in (("1h", 1), ("6h", 1), ("1d", 1), ("6h", 4), ("1h", 4)):
        d = root / f"{step}-{threads}"
        run_to_dataset(MIXED, "sample", [f"engine.step={step!r}",
                                          "engine.parallel_min_partitions=1"],
                       out_dir=d, threads=threads)
        out[(step, threads)] = d
    return out


def test_population_owners_of_a_created_type_key_by_partition_id(mixed_runs):
    """A `child_of` owner type with population and created owners: the population pays' tied
    asks (same time, prio, cause and src_seq) run in partition_id order whatever the step
    length or thread count (the created flag is per slot, not per type)."""
    orders = {}
    for run, d in mixed_runs.items():
        asked = read_events(d)["asked"].sort("event_time", "lamport", "partition_id", "seq")
        assert asked.height == 2 and asked["event_time"].dt.hour().to_list() == [1] * 2, run
        orders[run] = asked["v"].to_list()
    assert set(map(tuple, orders.values())) == {(0, 1)}, orders
