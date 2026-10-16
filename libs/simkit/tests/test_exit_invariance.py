"""Spec §10/§12 exit test: identical logical records across 1, 4 and 16 threads, two slab sizes
and two step lengths; identical replay is byte-identical."""

import itertools
import json
from collections import Counter
from pathlib import Path

import polars as pl
import pytest
from conftest import dataset_tree, event_dicts

from neorisk_simkit.engine.codegen import NEED_SWAP
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events
from neorisk_simkit.io.schema.schema_json import load_schema
from neorisk_simkit.spec.project import load_project, resolve_run

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s1"
SMALL = ["users=1500", "skus=300", "sku_groups=8", "run.span=4d", "run.warmup=1d",
         "journey.kyc_start_p=0.3", "engine.adapt=false",
         # engine pools sized for 1.5k users (the project's are sized for the 2M-user full run)
         "engine.timer_nodes=300_000", "engine.payload_slots=100_000",
         "engine.max_messages_per_step=200_000"]
THREADS = (1, 4, 16)
SLABS = ("8MB", "16KB")             # 16KB forces constant slab swaps (RETRY path)
STEPS = ("6h", "1d")
KEY = ["event_time", "lamport", "partition_id", "seq"]
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


def created_namespaces() -> frozenset[str]:
    """The ID namespaces the engine hands out at seal (creatable tables and `ids`): only their
    dense indices legitimately depend on step boundaries (D13). Population and static IDs
    (`user`, `sku`, `device`) and partition IDs are fixed before the run starts."""
    return frozenset(resolve_run(load_project(EX), "sample", SMALL).plan.namespaces)


def canonicalize_ids(d: Path) -> dict[str, list[dict]]:
    """Rename every created ID namespace by first appearance in global canonical order and
    number events by their canonical position (D13); every other column is kept as is."""
    created = created_namespaces()
    schema, events = load_schema(d), read_events(d)
    refs = {t["name"]: {c["name"]: c["ref"] for c in t["columns"]
                        if c.get("ref") in created}
            for t in schema["tables"] if t["kind"] == "event"}
    merged = pl.concat([
        e.select(*KEY, pl.lit(name).alias("_t"), pl.int_range(pl.len()).alias("_i"))
        for name, e in events.items() if e.height], how="vertical").sort(KEY)
    order = {(t, i): n for n, (t, i) in enumerate(zip(merged["_t"], merged["_i"]))}
    rename: dict[str, dict[int, int]] = {}
    out = {}
    for name, e in events.items():
        rows = e.to_dicts()
        for i, row in enumerate(rows):
            row["_pos"] = order[(name, i)]
        out[name] = rows
    flat = sorted(((r["_pos"], name, r) for name, rows in out.items() for r in rows),
                  key=lambda x: x[0])
    for _, name, row in flat:
        for col, ns in refs[name].items():
            v = row[col]
            if v is not None:
                row[col] = rename.setdefault(ns, {}).setdefault(v, len(rename[ns]))
        row["event_id"] = row.pop("_pos")
    return out


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
    created = created_namespaces()
    assert {"session", "checkout"} <= created and created.isdisjoint({"user", "sku", "device"})
    assert canonicalize_ids(dirs[(1, "8MB", "6h")]) == canonicalize_ids(dirs[(4, "16KB", "1d")])


def test_identical_replay_is_byte_identical(runs, tmp_path):
    dirs, _ = runs
    again = tmp_path / "again"
    run_to_dataset(EX, "sample", SMALL + ["engine.slab_bytes='8MB'", "engine.step='6h'"],
                   out_dir=again, threads=4, engine_overrides=ENGINE)
    assert dataset_tree(dirs[(4, "8MB", "6h")]) == dataset_tree(again)
