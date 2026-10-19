"""datagen check: report.html + checks.json, exit 5 on a failing required check (D86)."""

import json
from pathlib import Path

from datagen.cli import main
from neorisk_simkit.io.dataset import run_to_dataset

FIX = Path(__file__).resolve().parents[3] / "libs" / "simkit" / "tests" / "fixtures"


def _ring(tmp_path):
    proj = tmp_path / "ring"
    import shutil
    shutil.copytree(FIX / "ring", proj, ignore=shutil.ignore_patterns("out", "__pycache__"))
    (proj / "specs" / "expectations.yaml").write_text("""
pack: ring
defaults: {min_sample: 1}
laws: []
expectations:
  - id: exp.signups
    metric: stat.share("bonus_paid", of=["signed_up"])
    target: {between: [0.0, 1.0]}
    source: "test"
    required: true
overlays:
  ring:
    - id: exp.gangs
      metric: stat.cohort_size("gang")
      target: {around: "${ring.size}", tolerance: 0.0}
      source: "overlay config"
      required: true
    - id: exp.intf
      metric: stat.interference(base="bonus_paid", cause="pot")
      target: {reported: true}
      source: "§08"
      required: true
""")
    return proj


def test_check_writes_the_report_and_passes(tmp_path):
    proj = _ring(tmp_path)
    run_to_dataset(proj, "sample", [], threads=2)
    run_to_dataset(proj, "sample", [], overlays=["ring"], threads=2)
    rc = main(["check", str(proj), "--profile", "sample", "--overlay", "ring"])
    assert rc == 0
    out = proj / "reports" / "sample-s7+ring"
    html = (out / "report.html").read_text()
    for section in ("Counts", "Linkages", "Transitions", "Concentration", "Rejections",
                    "Cohorts", "Interference", "Checks"):
        assert f">{section}<" in html, section
    checks = json.loads((out / "checks.json").read_text())
    assert checks["ok"] is True and checks["interference"]["shared"] == ["pot"]
    # sections in the order of §02/§16, self-contained (no script, no external resource)
    pos = [html.index(f">{s}<") for s in ("Counts", "Linkages", "Transitions",
                                          "Concentration", "Rejections", "Cohorts",
                                          "Interference", "Checks")]
    assert pos == sorted(pos)
    assert "<script" not in html and "http://" not in html and "https://" not in html
    assert checks["run"] == "sample-s7+ring" and checks["pack"] == "ring"
    assert checks["overlays"] == {"ring": {"arrive_day": 0.0, "minions": 2, "share_device": 0.5,
                                           "size": 2, "wait": "2h"}}
    assert {r["id"] for r in checks["results"]} == {"exp.signups", "exp.gangs", "exp.intf"}
    # the shared partition's knock-on changes are explained, not styled as failures
    assert "knock-on" in html
    # a checked run of the same plan without overlays writes its own report (no interference)
    assert main(["check", str(proj), "--profile", "sample"]) == 0
    base = json.loads((proj / "reports" / "sample-s7" / "checks.json").read_text())
    assert base["interference"] is None and [r["id"] for r in base["results"]] == ["exp.signups"]


def test_a_missing_baseline_fails_the_required_interference_check(tmp_path):
    proj = _ring(tmp_path)
    run_to_dataset(proj, "sample", [], overlays=["ring"], threads=2)
    assert main(["check", str(proj), "--profile", "sample", "--overlay", "ring"]) == 5
    checks = json.loads((proj / "reports" / "sample-s7+ring" / "checks.json").read_text())
    st = {r["id"]: r["status"] for r in checks["results"]}
    assert st["exp.intf"] == "missing" and checks["ok"] is False
    html = (proj / "reports" / "sample-s7+ring" / "report.html").read_text()
    assert "interference needs a baseline run" in html            # the row's note is shown
    # usage errors exit 2: overlay parameters that differ from the run's, no such run,
    # a baseline folder that does not exist
    assert main(["check", str(proj), "--profile", "sample", "--overlay", "ring",
                 "--set", "ring.size=3"]) == 2
    assert main(["check", str(proj), "--profile", "sample"]) == 2
    assert main(["check", str(proj), "--profile", "sample", "--overlay", "ring",
                 "--baseline", str(tmp_path / "nope")]) == 2


def test_render_escapes_every_value(tmp_path):
    from neorisk_simkit.report import render

    evil = "<img src=x onerror=alert(1)>"
    (tmp_path / "manifest.json").write_text(json.dumps({
        "counts": {evil: 3}, "posting_counts": {}, "label_counts": {}, "entity_counts": {},
        "history_counts": {}, "pairing": {evil: {"requests": 1, "responses": 1}},
        "late_messages": 0, "pack": evil, "pack_revision": "r", "overlays": {}}))
    (tmp_path / "run_stats.json").write_text(json.dumps({"rejects": {evil: 1}, "machines": {}}))
    results = [{"id": evil, "kind": "expectation", "metric": evil, "value": 0.5,
                "ci": [0.4, 0.6], "n_cases": 10, "censored_share": 0.0,
                "target": {"between": [0, 1]}, "status": "pass", "required": True,
                "source": evil, "note": evil}]
    html = render(tmp_path, results, interference=None, plan=None)
    assert evil not in html and "&lt;img src=x onerror=alert(1)&gt;" in html
