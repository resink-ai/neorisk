import json
from pathlib import Path

from datagen.benchmark import evaluate, load_workload
from datagen.cli import main

S1 = Path(__file__).resolve().parents[3] / "benchmarks" / "s1.toml"


def _stats(**kw):
    base = {"engine_seconds": 50.0, "peak_rss_bytes": 8 * 1024**3, "exported_events": 10_100_000,
            "proposals": 40_000_000, "requests_by_boundary": {"reserve": 3_300_000},
            "threads": 16, "machine": {"arch": "x86_64", "cpus": 16, "ram_bytes": 64 * 1024**3}}
    return base | kw


def test_workload_loads():
    wl = load_workload(S1)
    assert wl.project.name == "ecommerce_s1" and wl.profile == "full" and wl.seed == 42
    assert wl.gate["warm_seconds"] == 60 and wl.gate["peak_rss_gb"] == 16


def test_gate_pass_and_fail():
    wl = load_workload(S1)
    assert evaluate(_stats(), wl, scale=1.0)["verdict"] == "pass"
    assert evaluate(_stats(engine_seconds=61.0), wl, scale=1.0)["verdict"] == "fail"
    assert evaluate(_stats(peak_rss_bytes=17 * 1024**3), wl, scale=1.0)["verdict"] == "fail"
    assert evaluate(_stats(exported_events=8_000_000), wl, scale=1.0)["verdict"] == "fail"
    r = evaluate(_stats(machine={"arch": "arm64", "cpus": 14, "ram_bytes": 36 * 1024**3}), wl,
                 scale=1.0)
    assert r["reference_hardware"] is False
    assert evaluate(_stats(), wl, scale=0.01)["verdict"] == "skipped"


def test_scaled_smoke_run(tmp_path):
    out = tmp_path / "report.json"
    assert main(["benchmark", str(S1), "--scale", "0.002", "--threads", "4",
                 "--out", str(out)]) == 0
    rep = json.loads(out.read_text())
    for key in ("engine_seconds", "cold_compile_seconds", "peak_rss_bytes", "exported_events",
                "stage_seconds", "rounds_per_step", "verdict"):
        assert key in rep, key
    assert rep["verdict"] == "skipped" and rep["exported_events"] > 0
    reserves = rep["requests_by_boundary"]["reserve"]
    assert 0 < reserves < rep["proposals"]
    assert rep["inventory_share_of_proposals"] == reserves / rep["proposals"]


def test_failing_child_keeps_its_exit_code(tmp_path, monkeypatch):
    """D35: a validation error in the benchmark child exits 2 (not 1), CapExceeded exits 3."""
    import datagen.benchmark as bm

    wl = tmp_path / "bad.toml"
    wl.write_text(f'[workload]\nname = "bad"\nproject = "{S1.parent / "../examples/ecommerce_s1"}"\n'
                  'profile = "sample"\nset = ["no_such_knob=1"]\n[gate]\nwarm_seconds = 60\n')
    assert main(["benchmark", str(wl), "--out", str(tmp_path / "r.json")]) == 2

    def cap_exceeded(cmd, env):
        raise bm.ChildFailed(3, cmd)

    monkeypatch.setattr(bm, "_run_child", cap_exceeded)
    assert main(["benchmark", str(S1), "--out", str(tmp_path / "r.json")]) == 3


def test_memory_is_reported_in_gib():
    r = evaluate(_stats(peak_rss_bytes=8 * 1024**3), load_workload(S1), scale=1.0)
    rss = next(c for c in r["checks"] if c["name"] == "peak_rss_gib")
    assert rss["value"] == 8.0 and rss["limit"] == 16.0
