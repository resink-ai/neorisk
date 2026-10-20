"""datagen check: checks.json, exit codes, anchoring to the pack revision."""

import json
import shutil
from pathlib import Path

import polars as pl
import pytest

from datagen.cli import main

PAY = Path(__file__).resolve().parents[3] / "examples" / "payments"


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "payments"
    shutil.copytree(PAY, proj, ignore=shutil.ignore_patterns("out", "reports", "__pycache__"))
    assert main(["run", str(proj), "--set", "customers=150", "--set", "run.days=40"]) == 0
    return proj


def _report(proj):
    return json.loads((proj / "reports" / "default-s7" / "checks.json").read_text())


def test_clean_run_passes_and_writes_checks_json(project, capsys):
    assert main(["check", str(project / "out" / "default-s7"), "--skip-stats"]) == 0
    rep = _report(project)
    assert rep["failed"] == []
    names = {r["name"] for r in rep["results"]}
    assert {"s.anchored", "s.types", "refunds_le_captured", "credit_limit_respected"} <= names
    assert all(r["status"] == "pass" for r in rep["results"])


def test_a_broken_law_fails_and_cites_the_row(project):
    f = project / "out" / "default-s7" / "events" / "refund_issued.parquet"
    df = pl.read_parquet(f)
    assert df.height > 0
    df.with_columns(amount=pl.col("amount") * 1000).write_parquet(f)
    assert main(["check", str(project / "out" / "default-s7"), "--skip-stats"]) == 1
    rep = _report(project)
    assert "refunds_le_captured" in rep["failed"]
    bad = next(r for r in rep["results"] if r["name"] == "refunds_le_captured")
    assert bad["cited"][0]["action"].startswith("payment.") and "seq" in bad["cited"][0]


def test_edited_specs_make_the_run_unanchored(project):
    pack = project / "specs" / "pack.py"
    pack.write_text(pack.read_text() + "\n# edited\n")
    assert main(["check", str(project / "out" / "default-s7"), "--skip-stats"]) == 1
    assert _report(project)["failed"] == ["s.anchored"]


def test_check_needs_a_project(tmp_path, project):
    run = tmp_path / "elsewhere" / "x"
    shutil.copytree(project / "out" / "default-s7", run)
    assert main(["check", str(run), "--skip-stats"]) == 2
    assert main(["check", str(run), "--project", str(project), "--skip-stats"]) == 0


def test_full_check_with_expectations_and_held_out_seeds(tmp_path):
    proj = tmp_path / "payments"
    shutil.copytree(PAY, proj, ignore=shutil.ignore_patterns("out", "reports", "__pycache__"))
    assert main(["run", str(proj)]) == 0
    assert main(["check", str(proj / "out" / "default-s7"), "--seeds", "2"]) == 0
    rep = _report(proj)
    exp = {r["name"]: r for r in rep["results"] if r["group"] == "stat"}
    assert exp["exp.refund_rate"]["status"] == "pass"
    lo, hi = exp["exp.refund_rate"]["metric"]["ci95"]
    assert lo <= exp["exp.refund_rate"]["metric"]["value"] + 0.02 and lo < hi
    assert (proj / "reports" / "default-s7" / "report.html").exists()
