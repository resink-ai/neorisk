"""Spec §05 exit test: native ABI proof.

A compiled kernel that emits several record types, creates rows, schedules timers and requests,
and rejects, runs under forced exhaustion of each resource in turn, compiled with checked mode and
uncompiled, and must produce identical logical output.
"""

import json
import os
import subprocess
import sys
from collections import Counter

import polars as pl
import pytest
from conftest import FIXTURES, event_dicts

from neorisk_simkit.engine.codegen import NEED_NODES, NEED_SWAP
from neorisk_simkit.engine.world import World
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.read import read_events

PROJECT = FIXTURES / "abi_proof"
MINIMA = {"records:e_alpha": 1, "records:e_beta": 1, "records:e_gamma": 2, "creates:box": 1,
          "creates:tok": 1, "timers": 2, "requests": 1}


def logical(out_dir):
    """Every event table and the created-row entities, as comparable Python objects."""
    data = event_dicts(out_dir)
    data["entities/box"] = pl.read_parquet(out_dir / "entities/box/part-00000.parquet").to_dicts()
    return data


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    out = tmp_path_factory.mktemp("abi") / "baseline"
    run_to_dataset(PROJECT, "sample", out_dir=out, threads=2)
    return out


def test_baseline_exercises_every_path(baseline):
    m = json.loads((baseline / "manifest.json").read_text())
    stats = json.loads((baseline / "run_stats.json").read_text())
    assert m["counts"]["e_alpha"] > 0 and m["counts"]["e_beta"] == m["counts"]["e_alpha"]
    assert m["counts"]["sunk"] > 0 and m["counts"]["e_gamma"] > 2 * m["counts"]["e_alpha"]
    assert stats["rejects"]["prove"] > 0
    ev = read_events(baseline)
    assert ev["e_gamma"]["note"].null_count() < ev["e_gamma"].height
    assert 0 < ev["e_gamma"]["note"].null_count()


@pytest.fixture
def statuses(monkeypatch):
    """Spy on the runner statuses World handles: Counter of (status, missed resource or None)."""
    seen = Counter()
    real = World.handle_status

    def spy(self, worker, status):
        m = int(self.slabs[worker].miss[0])
        seen[status, self.slabs[worker].resources[m] if m >= 0 else None] += 1
        return real(self, worker, status)

    monkeypatch.setattr(World, "handle_status", spy)
    return seen


@pytest.mark.parametrize("resource", sorted(MINIMA))
def test_forced_exhaustion_matches_baseline(resource, baseline, tmp_path, statuses):
    r = run_to_dataset(PROJECT, "sample", out_dir=tmp_path / "forced", threads=2,
                       engine_overrides={"force_capacity": {resource: MINIMA[resource]}})
    base = json.loads((baseline / "run_stats.json").read_text())
    assert r.stats["retries"] > base["retries"], f"{resource} was never exhausted"
    if resource == "timers":                 # the capped node free list forces refills
        assert sum(n for (st, _), n in statuses.items() if st == NEED_NODES) > 10 * base["retries"]
    else:                                    # the forced buffer filled and was swapped/moved aside
        assert statuses[NEED_SWAP, resource] > 0, dict(statuses)
    assert logical(r.out_dir) == logical(baseline)


SCRIPT = """
import sys
from pathlib import Path
from neorisk_simkit.io.dataset import run_to_dataset
project, root, minima = Path(sys.argv[1]), Path(sys.argv[2]), eval(sys.argv[3])
run_to_dataset(project, "sample", out_dir=root / "all", threads=1, checked=True)
for res, n in minima.items():
    run_to_dataset(project, "sample", out_dir=root / res.replace(":", "_"), threads=1,
                   checked=True, engine_overrides={"force_capacity": {res: n}})
"""


@pytest.mark.checked
@pytest.mark.parametrize("mode", ["checked", "uncompiled"])
def test_checked_and_uncompiled_runs_match(mode, baseline, tmp_path):
    env = dict(os.environ)
    if mode == "checked":
        env["NUMBA_BOUNDSCHECK"] = "1"
        env["NUMBA_CACHE_DIR"] = str(tmp_path.parent / "numba-checked-cache")
    else:
        env["NUMBA_DISABLE_JIT"] = "1"
    subprocess.run([sys.executable, "-c", SCRIPT, str(PROJECT), str(tmp_path), repr(MINIMA)],
                   env=env, check=True, timeout=3600)
    want = logical(baseline)
    assert logical(tmp_path / "all") == want

    def retries(d):
        return json.loads((tmp_path / d / "run_stats.json").read_text())["retries"]

    for res in MINIMA:
        d = res.replace(":", "_")
        assert retries(d) > retries("all"), f"{res} was never exhausted"
        assert logical(tmp_path / d) == want, res
