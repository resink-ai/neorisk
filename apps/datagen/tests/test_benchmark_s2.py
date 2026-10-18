import json
from pathlib import Path

from datagen.benchmark import derived, evaluate, load_workload
from datagen.cli import main

ROOT = Path(__file__).resolve().parents[3] / "benchmarks"
S2, POOL = ROOT / "s2.toml", ROOT / "s2_pool.toml"
GIB = 1024**3


def _stats(**kw):
    base = {"engine_seconds": 500.0, "peak_rss_bytes": 20 * GIB, "exported_events": 101_000_000,
            "events_per_second": 202_000.0, "shard_events_per_second": 120_000.0,
            "shard_phase_seconds": 250.0, "shard_events": 30_000_000,
            "proposals": 300_000_000, "commands": 400_000_000,
            "shard_command_share": 0.25, "requests_by_boundary": {"reserve": 9_000_000},
            "counts": {"payment_authorized": 29_000_000, "payment_declined": 900_000,
                       "checkout_started": 10_000_000},
            "accumulators": {"hot_checkouts": 500_000},
            "posting_counts": {"ledger": 150_000_000},
            "events_by_partition": {"payment": 60_000_000},
            "shard_load": {"inventory": {"requests": [450_000] + [10] * 511}},
            "populations": {"user": 2_000_000, "campaign": 5_000},
            "ids_allocated": {"member": 15_000},
            "threads": 16, "machine": {"arch": "x86_64", "cpus": 16, "ram_bytes": 64 * GIB}}
    return base | kw


def test_workloads_load():
    s2, pool = load_workload(S2), load_workload(POOL)
    assert s2.project.name == pool.project.name == "ecommerce_s2"
    assert (s2.profile, pool.profile) == ("full", "pool")
    assert s2.gate["warm_seconds"] == 600 and pool.gate["min_events_per_second"] == 80_000
    assert pool.gate["min_shard_events_per_second"] == 80_000


def test_derived_values():
    d = derived(_stats())
    assert d["payments"] == 29_900_000
    assert d["postings_per_payment_event"] == 2.5
    assert d["hot_share_of_checkouts"] == 0.05
    assert abs(d["hot_share_of_reserves"] - 450_000 / (450_000 + 5_110)) < 1e-12
    assert d["campaign_member_share"] == (5_000 + 15_000) / 2_000_000
    assert "payments" not in derived({"proposals": 1})           # S1 reports unchanged


def test_derived_values_need_their_inputs():
    """Task 20 M1/M3: the hot reserve share needs the `hot_checkouts` accumulator (S1 also has an
    `inventory` shard, with no hot group), the member share needs `ids_allocated.member`."""
    st = _stats()
    del st["accumulators"]
    del st["ids_allocated"]
    d = derived(st)
    assert "hot_share_of_reserves" not in d and "campaign_member_share" not in d


def test_at_most_and_a_malformed_expectation(tmp_path, capsys):
    """Task 20 M2: the `at_most` form, and a malformed form refused before any run (exit 1)."""
    import dataclasses

    import pytest

    wl = dataclasses.replace(load_workload(POOL), expect={"shard_command_share": {"at_most": 0.3}})
    over = evaluate(_stats(), wl, scale=1.0)
    assert [(c["ok"], c["limit"]) for c in over["checks"]
            if c["name"] == "shard_command_share"] == [(True, [None, 0.3])]
    under = evaluate(_stats(shard_command_share=0.31), wl, scale=1.0)
    assert under["verdict"] == "fail"
    bad = tmp_path / "bad.toml"
    bad.write_text(POOL.read_text().replace(
        "shard_command_share = { at_least = 0.5 }", "shard_command_share = { at_leest = 0.5 }"))
    assert bad.read_text() != POOL.read_text()
    with pytest.raises(ValueError, match="expectation 'shard_command_share' must be"):
        load_workload(bad)
    assert main(["benchmark", str(bad)]) == 1
    assert "expectation 'shard_command_share' must be" in capsys.readouterr().err


def test_unavailable_shard_timing_is_not_measured_never_a_pass():
    """Codex fix-confirm CX5: without a compiled clock the run reports no shard-phase rate;
    the shard gate is then "not measured", and the verdict is never `pass`."""
    from datagen.benchmark import summary

    wl = load_workload(POOL)
    ok = _stats(exported_events=10_100_000, events_per_second=90_000.0,
                shard_events_per_second=None, shard_command_share=0.6,
                shard_timing="unavailable: no compiled clock on win32")
    r = evaluate(ok, wl, scale=1.0)
    c = next(c for c in r["checks"] if c["name"] == "shard_events_per_second")
    assert (c["ok"], c["status"], c["value"]) == (None, "not measured", None)
    assert c["reason"] == "unavailable: no compiled clock on win32"
    assert r["verdict"] == "not measured"
    assert evaluate(ok | {"events_per_second": 1.0}, wl, scale=1.0)["verdict"] == "fail"
    text = summary(r | ok | {"report_path": "x.json", "cold": False, "workload": "s2_pool",
                             "scale": 1.0, "engine_seconds": 1.0, "cold_compile_seconds": 1.0,
                             "stage_seconds": {}, "rounds_per_step": [1], "machine": {},
                             "shard_load": {}})
    assert "NOT MEASURED (unavailable: no compiled clock on win32)" in text
    assert "verdict           not measured" in text


def test_s2_gate():
    wl = load_workload(S2)
    ok = _stats()                                    # the reserve share is not an expectation
    assert evaluate(ok, wl, scale=1.0)["verdict"] == "pass"
    assert evaluate(ok | {"engine_seconds": 601.0}, wl, scale=1.0)["verdict"] == "fail"
    cold = evaluate(ok | {"accumulators": {"hot_checkouts": 700_000}}, wl, scale=1.0)
    c = next(c for c in cold["checks"] if c["name"] == "hot_share_of_checkouts")
    assert not c["ok"]                               # 0.07 is outside 0.05 ± 0.01


def test_pool_gate_and_at_least():
    wl = load_workload(POOL)
    ok = _stats(exported_events=10_100_000, events_per_second=90_000.0,
                shard_events_per_second=95_000.0, shard_command_share=0.6)
    r = evaluate(ok, wl, scale=1.0)
    assert r["verdict"] == "pass", r["checks"]
    assert evaluate(ok | {"events_per_second": 79_999.0}, wl, scale=1.0)["verdict"] == "fail"
    assert evaluate(ok | {"shard_events_per_second": 79_999.0}, wl,
                    scale=1.0)["verdict"] == "fail"
    low = evaluate(ok | {"shard_command_share": 0.45}, wl, scale=1.0)
    c = next(c for c in low["checks"] if c["name"] == "shard_command_share")
    assert not c["ok"] and c["limit"] == [0.5, None]


def test_s2_profiles_validate():
    from neorisk_simkit.spec.project import load_project, resolve_run
    from neorisk_simkit.spec.validate import validate
    for wl in (load_workload(S2), load_workload(POOL)):
        rep = validate(resolve_run(load_project(wl.project), wl.profile, []))
        assert rep.ok, (wl.name, rep.errors)


def test_pool_scaled_smoke_run(tmp_path):
    out = tmp_path / "report.json"
    assert main(["benchmark", str(POOL), "--scale", "0.001", "--threads", "4",
                 "--out", str(out)]) == 0
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "skipped" and rep["exported_events"] > 0
    for k in ("shard_command_share", "shard_load", "campaign_member_share", "events_per_second",
              "shard_events_per_second", "hot_share_of_checkouts"):
        assert k in rep, k
