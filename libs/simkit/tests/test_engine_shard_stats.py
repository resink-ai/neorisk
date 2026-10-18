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


def test_clock_falls_back_to_zero_without_a_compiled_clock():
    """Task 19 M1: a platform other than macOS or Linux gets the constant 0 (compiled shard
    phases go untimed) instead of a TypingError that would break the compiled engine."""
    from llvmlite import ir

    from neorisk_simkit.engine.clock import clock_ir, clock_source

    assert clock_source("darwin") == "clock_gettime_nsec_np"
    assert clock_source("linux") == "clock_gettime"
    assert clock_source("win32") is None and clock_source("freebsd14") is None
    emitted = {}
    for source in ("clock_gettime_nsec_np", "clock_gettime", None):
        mod = ir.Module()
        fn = ir.Function(mod, ir.FunctionType(ir.IntType(64), []), "now")
        b = ir.IRBuilder(fn.append_basic_block())
        b.ret(clock_ir(b, source))
        emitted[source] = str(mod)
    assert "ret i64 0" in emitted[None] and "declare" not in emitted[None]
    assert '@"clock_gettime_nsec_np"(i32 8)' in emitted["clock_gettime_nsec_np"]
    assert '@"clock_gettime"(i32 1' in emitted["clock_gettime"]


def test_compiled_rounds_time_their_shard_phases(monkeypatch, tmp_path):
    """Task 19 M2: with Python rounds' timer stopped, the shard-phase time comes from the
    compiled drain alone, and it is nonzero."""
    from types import SimpleNamespace

    from neorisk_simkit.engine import rounds

    monkeypatch.setattr(rounds, "time", SimpleNamespace(perf_counter_ns=lambda: 0))
    r = run_to_dataset(FIXTURES / "mini", "sample", ["behavior.take_p=0.8"],
                       out_dir=tmp_path / "run", threads=1,
                       engine_overrides={"parallel_min_partitions": 10**9})
    st = json.loads((r.out_dir / "run_stats.json").read_text())
    assert st["compiled_rounds_total"] > 0 and st["shard_events"] > 0
    assert st["shard_phase_seconds"] > 0


def test_shard_timing_is_unavailable_without_a_compiled_clock(monkeypatch, tmp_path):
    """Codex fix-confirm CX5: where `clock_ns` compiles to 0, compiled shard phases go
    untimed, so the run reports no shard-phase rate (null, with the reason) rather than a rate
    over Python rounds alone."""
    from neorisk_simkit.engine import clock

    assert clock.compiled_clock_available()               # macOS or Linux here
    monkeypatch.setattr(clock, "clock_source", lambda platform: None)
    assert not clock.compiled_clock_available()
    r = run_to_dataset(FIXTURES / "mini", "sample", ["behavior.take_p=0.8"],
                       out_dir=tmp_path / "run", threads=1)
    st = json.loads((r.out_dir / "run_stats.json").read_text())
    assert st["shard_events_per_second"] is None
    assert st["shard_timing"].startswith("unavailable: no compiled clock on ")
    assert st["shard_events"] > 0


def test_shard_timing_is_measured_with_a_compiled_clock(mini):
    st, _ = mini
    assert st["shard_timing"] == "measured"
