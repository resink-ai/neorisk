import json
from pathlib import Path

import polars as pl

from datagen.cli import main

ECOM = str(Path(__file__).resolve().parents[3] / "examples" / "ecommerce")
SMALL = ["--set", "users=300", "--set", "run.days=10"]


def _files(d: Path) -> dict[str, bytes]:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*"))
            if p.is_file() and p.name != "run_stats.json"}


def test_run_writes_the_layout_and_replays_byte_identically(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        assert main(["run", ECOM, "--overlay", "bounty_hunters", *SMALL, "--out", str(d)]) == 0
    fa = _files(a)
    assert fa == _files(b)
    for f in ("manifest.json", "schema/schema.json", "events/order_placed.parquet",
              "entities/users.parquet", "labels/labels.parquet", "cases/cases.parquet"):
        assert f in fa
    m = json.loads((a / "manifest.json").read_text())
    assert m["pack"] == "ecommerce" and m["seed"] == 7 and m["config"]["users"] == 300
    assert m["overlays"] == {"bounty_hunters": {"share": 0.002, "zombies_mean": 8.0}}
    assert m["provenance"]["pack_revision"] and m["files"]["events/order_placed.parquet"]
    assert json.loads((a / "run_stats.json").read_text())["peak_rss_mb"] > 0


def test_existing_run_needs_force(tmp_path):
    out = str(tmp_path / "r")
    assert main(["run", ECOM, *SMALL, "--out", out]) == 0
    assert main(["run", ECOM, *SMALL, "--out", out]) == 2
    assert main(["run", ECOM, *SMALL, "--out", out, "--force"]) == 0


def test_default_out_dir_names_profile_seed_and_overlays(tmp_path):
    import shutil
    proj = tmp_path / "ecommerce"
    shutil.copytree(ECOM, proj, ignore=shutil.ignore_patterns("out", "__pycache__"))
    assert main(["run", str(proj), "--profile", "sample", "--overlay", "bounty_hunters",
                 "--seed", "42", *SMALL]) == 0
    assert (proj / "out" / "sample-s42+bounty_hunters" / "manifest.json").exists()


def test_validate_and_usage_errors(tmp_path, capsys):
    assert main(["validate", ECOM, "--overlay", "bounty_hunters"]) == 0
    assert main(["run", ECOM, "--profile", "nope"]) == 2
    assert main(["run", ECOM, "--set", "nonsense=1"]) == 2
    assert main(["run", ECOM, "--set", "bounty_hunters.share=1"]) == 2   # overlay not in run
    assert main(["run", ECOM, "--overlay", "nope"]) == 2
    assert main(["export", str(tmp_path), "--out", str(tmp_path / "x")]) == 2
    assert main(["check", str(tmp_path / "nope"), "--project", ECOM]) == 2
    assert main(["replay", str(tmp_path / "nope")]) == 2
    assert main(["run", str(tmp_path / "no_project")]) == 2


def test_debug_run_and_exports(tmp_path):
    run, fraud, one = tmp_path / "run", tmp_path / "fraud", tmp_path / "all.parquet"
    assert main(["run", ECOM, "--overlay", "bounty_hunters", "--debug", *SMALL,
                 "--set", "users=600", "--out", str(run)]) == 0
    assert main(["export", str(run), "--legacy-fraud", "--out", str(fraud)]) == 0
    meta = json.loads((fraud / "meta.json").read_text())
    assert meta["n_events"] > 0 and meta["feature_allowlist"]
    assert meta["source"]["overlays"] == {"bounty_hunters": {"share": 0.002, "zombies_mean": 8.0}}
    scored = tmp_path / "scored"
    assert main(["export", str(run), "--legacy-fraud", "--labels", "xgb", "--bad-rate", "0.1",
                 "--out", str(scored)]) == 0
    labels = json.loads((scored / "meta.json").read_text())["labels"]
    assert labels["source"] == "scorer" and labels["target_bad_rate"] == 0.1
    assert main(["export", str(run), "--legacy-fraud", "--labels", "xgb", "--bad-rate", "1",
                 "--out", str(tmp_path / "bad")]) == 2
    assert main(["export", str(run), "--single-file", str(one)]) == 0
    df = pl.read_parquet(one)
    assert df["seq"].is_sorted() and df["event_type"].n_unique() >= 6
