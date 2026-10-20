import json

from datagen.cli import main


def test_run_then_export(tmp_path):
    run, out = tmp_path / "run", tmp_path / "fraud"
    assert main(["run", "--out", str(run), "--users", "600", "--days", "20"]) == 0
    assert (run / "order_placed.parquet").exists()
    assert main(["export", str(run), "--legacy-fraud", "--out", str(out)]) == 0
    meta = json.loads((out / "meta.json").read_text())
    assert meta["n_events"] > 0 and meta["feature_allowlist"]


def test_export_needs_legacy_fraud(tmp_path):
    assert main(["export", str(tmp_path), "--out", str(tmp_path / "x")]) == 2
