import json
import time

import pytest
from conftest import FIXTURES
from numba import njit

from neorisk_simkit.engine.clock import clock_ns
from neorisk_simkit.io.dataset import run_to_dataset


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    r = run_to_dataset(FIXTURES / "mini", "sample", ["behavior.take_p=0.8"],
                       out_dir=tmp_path_factory.mktemp("load") / "run", threads=1)
    return json.loads((r.out_dir / "run_stats.json").read_text()), json.loads(
        (r.out_dir / "manifest.json").read_text())


def test_shard_load_is_reported_per_shard(mini):
    st, _ = mini
    load =st["shard_load"]["bin"]
    assert load["shards"] == 4 and len(load["requests"]) == len(load["commands"]) == 4
    assert sum(load["requests"]) == st["requests_by_boundary"]["take"]
    assert sum(load["commands"]) == st["shard_commands"] >= sum(load["requests"])
    assert 0 < load["max_share"] <= 1


def test_command_shares_and_round_totals(mini):
    st, _ = mini
    assert st["commands"] == st["proposals"] + st["shard_commands"]
    assert st["shard_command_share"] == st["shard_commands"] / st["commands"]
    assert st["rounds_total"] == sum(st["rounds_per_step"]) >= st["compiled_rounds_total"]


def test_output_is_counted_by_kind_and_partition(mini):
    st, m = mini
    assert st["counts"] == m["counts"] and st["entity_counts"] == m["entity_counts"]
    assert st["posting_counts"] == m["posting_counts"] == {}
    assert st["accumulators"] == m["accumulators"] == {}
    assert sum(st["events_by_partition"].values()) == st["exported_events"]
    assert set(st["events_by_partition"]) == {"user", "bin"}
    assert st["populations"] == {"user": 200}


def test_shard_phase_rate_is_reported(mini):
    """D55 / F-03: shard-emitted exported events over the seconds spent in shard phases."""
    st, _ = mini
    assert st["shard_phase_seconds"] > 0
    assert st["shard_events"] == st["events_by_partition"]["bin"] > 0
    assert st["shard_events_per_second"] == st["shard_events"] / st["shard_phase_seconds"]


def test_admissions_are_counted(tmp_path):
    r = run_to_dataset(FIXTURES / "chain", "sample", out_dir=tmp_path / "c", threads=1)
    st = json.loads((r.out_dir / "run_stats.json").read_text())
    assert st["admissions_total"] == 8                    # 4 b + 4 c
    assert st["ids_allocated"] == {"b": 4, "c": 4}


def test_compiled_clock_reads_the_perf_counter_clock():
    """The compiled shard-phase timer (`engine.clock.clock_ns`) reads the clock Python rounds
    time with (`time.perf_counter_ns`), so both paths add comparable nanoseconds."""
    now = njit(lambda: clock_ns())
    now()
    a = time.perf_counter_ns()
    c = now()
    b = time.perf_counter_ns()
    assert a <= c <= b
