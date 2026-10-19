"""`--overlay NAME` / `--no-overlays` on validate, run and schema (D77, F-15, D95)."""

import json
from pathlib import Path

from datagen.cli import main

FIXTURES = Path(__file__).resolve().parents[3] / "libs" / "simkit" / "tests" / "fixtures"
RING = FIXTURES / "ring"


def _overlays_line(out: str) -> str | None:
    return next((ln for ln in out.splitlines() if ln.startswith("overlays: ")), None)


def test_validate_takes_the_profile_list_and_the_flags(capsys):
    assert main(["validate", str(RING), "--profile", "gang"]) == 0
    assert _overlays_line(capsys.readouterr().out) == "overlays: ring"
    assert main(["validate", str(RING), "--profile", "gang", "--no-overlays"]) == 0
    assert _overlays_line(capsys.readouterr().out) is None
    assert main(["validate", str(RING), "--overlay", "ring"]) == 0
    assert _overlays_line(capsys.readouterr().out) == "overlays: ring"
    assert main(["validate", str(RING), "--overlay", "nope"]) == 2
    assert "overlay 'nope'" in capsys.readouterr().err


def test_schema_sql_holds_overlay_tables_only_when_named(capsys):
    assert main(["schema", str(RING), "--profile", "gang"]) == 0
    base = capsys.readouterr().out
    assert "labels_gang" not in base and "signed_up" in base
    assert main(["schema", str(RING), "--profile", "gang", "--overlay", "ring"]) == 0
    assert "labels_gang" in capsys.readouterr().out
    assert main(["schema", str(RING), "--profile", "gang", "--format", "json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert {t["name"]: t["overlay"] for t in doc["tables"] if "overlay" in t} == {
        "gang": "ring", "labels_gang": "ring"}


def test_run_takes_the_overlay_flags(tmp_path, capsys):
    out = tmp_path / "o"
    assert main(["run", str(RING), "--overlay", "ring", "--set", "ring.size=1",
                 "--out", str(out)]) == 0
    assert "label labels_gang:" in capsys.readouterr().out
    m = json.loads((out / "manifest.json").read_text())
    assert m["overlays"]["ring"]["size"] == 1 and m["label_counts"]["labels_gang"] >= 1
    out = tmp_path / "b"
    assert main(["run", str(RING), "--profile", "gang", "--no-overlays", "--out", str(out)]) == 0
    m = json.loads((out / "manifest.json").read_text())
    assert m["overlays"] == {} and "labels_gang" not in m["label_counts"]
