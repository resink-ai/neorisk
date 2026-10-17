import json
import shutil
from pathlib import Path

import pytest

from datagen.cli import main

FIXTURES = Path(__file__).resolve().parents[3] / "libs" / "simkit" / "tests" / "fixtures"


@pytest.fixture
def mini(tmp_path):
    dst = tmp_path / "mini"
    shutil.copytree(FIXTURES / "mini", dst)
    return dst


def test_validate_ok_prints_caps(mini, capsys):
    assert main(["validate", str(mini)]) == 0
    out = capsys.readouterr().out
    assert "pack mini @" in out and "timer_heaps" in out and "estimate" in out and "OK" in out


def test_validate_reports_structural_errors(mini, capsys):
    pack = mini / "specs" / "pack.py"
    pack.write_text(pack.read_text().replace("dist.constant(ms=200)", "dist.constant(ms=0)"))
    assert main(["validate", str(mini)]) == 2
    assert "boundary take: minimum latency must be > 0" in capsys.readouterr().out


def test_run_writes_the_named_folder_and_refuses_to_overwrite(mini, capsys):
    assert main(["run", str(mini), "--set", "users=50"]) == 0
    run_dir = mini / "out" / "sample-s7"
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["overrides"] == ["users=50"] and manifest["seed"] == 7
    assert main(["run", str(mini), "--set", "users=50"]) == 2
    assert "already exists" in capsys.readouterr().err
    assert main(["run", str(mini), "--set", "users=50", "--force"]) == 0


def test_run_seed_threads_and_out(mini, tmp_path):
    out = tmp_path / "elsewhere"
    assert main(["run", str(mini), "--seed", "9", "--threads", "1", "--out", str(out)]) == 0
    assert json.loads((out / "manifest.json").read_text())["seed"] == 9


def test_cap_exceeded_exits_3(mini, capsys):
    assert main(["run", str(mini), "--set", "engine.timer_nodes=40"]) == 3
    assert "timer_heaps" in capsys.readouterr().err


def test_budget_refusal_exits_2(mini, capsys):
    assert main(["run", str(mini), "--set", "budget.memory='1MB'"]) == 2
    assert "exceed the memory budget" in capsys.readouterr().err


def test_threads_override_beyond_the_budget_exits_2(mini, capsys):
    from neorisk_simkit.spec.caps import compute_caps
    from neorisk_simkit.spec.project import load_project, resolve_run

    run = resolve_run(load_project(mini), "sample", [])
    fits = f"budget.memory={sum(c.hard_bytes for c in compute_caps(run))}"
    assert main(["run", str(mini), "--set", fits, "--threads", "64"]) == 2
    err = capsys.readouterr().err
    assert "exceed the memory budget" in err and "output_slabs" in err
    assert not (mini / "out" / "sample-s7").exists()
