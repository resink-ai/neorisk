import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from datagen.cli import main
from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.sinks.file import FileSink

EX = Path(__file__).resolve().parents[3] / "examples" / "ecommerce_s1"


@pytest.fixture(scope="module")
def ds(tmp_path_factory):
    proj = tmp_path_factory.mktemp("proj") / "ecommerce_s1"
    shutil.copytree(EX, proj, ignore=shutil.ignore_patterns("out", "reports", "logs"))
    r = run_to_dataset(proj, "sample", ["users=800", "skus=200", "sku_groups=4", "run.span=3d",
                                        "run.warmup=1d"],
                       out_dir=proj / "out" / "sample-s42")
    return r.out_dir


def test_first_to_stdout(ds, capsys):
    assert main(["replay", str(ds), "--first", "5"]) == 0
    cap = capsys.readouterr()
    rows = [json.loads(x) for x in cap.out.splitlines()]
    assert len(rows) == 5 and "rows" in cap.err and "stdout" in cap.err


def test_tee_to_stdout_and_file(ds, tmp_path, capsys):
    path = tmp_path / "last.json"
    assert main(["replay", str(ds), "--last", "7", "--sink", "stdout",
                 "--sink", f"file:{path}?format=json-array"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 7
    assert len(json.loads(path.read_text())) == 7


def test_types_window_and_numbers(ds, capsys):
    # the whole exported span (start 2026-01-01, run.span=3d), so the selection is not empty
    assert main(["replay", str(ds), "--types", "order_placed", "--from", "2026-01-01",
                 "--to", "2026-01-04", "--numbers"]) == 0
    rows = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert rows
    assert all(r["event_type"] == "order_placed" and isinstance(r["amount"], int) for r in rows)


def test_preset_from_project_file(ds, capsys):
    assert main(["replay", str(ds), "--preset", "peek"]) == 0
    assert capsys.readouterr().out.splitlines()[0].split()[0] == "event_id"


def test_explicit_flags_override_preset(ds, capsys):
    assert main(["replay", str(ds), "--preset", "peek", "--last", "4",
                 "--sink", "stdout"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 4


def test_bad_arguments_and_kafka(ds, capsys):
    assert main(["replay", str(ds), "--first", "1", "--last", "1"]) == 2
    assert main(["replay", str(ds), "--sink", "kafka://localhost:9092/t"]) == 2
    assert "arrives in M4" in capsys.readouterr().err
    assert main(["replay", str(ds), "--from", "yesterday"]) == 2
    assert main(["replay", str(ds), "--preset", "nope"]) == 2
    assert main(["replay", str(ds / "missing")]) == 2


def test_empty_selections_exit_zero_and_write_empty_array(ds, tmp_path, capsys):
    for i, extra in enumerate((["--from", "2030-01-01"], ["--to", "2000-01-01"])):
        path = tmp_path / f"empty{i}.json"
        assert main(["replay", str(ds), *extra, "--sink", f"file:{path}"]) == 0
        assert json.loads(path.read_text()) == []
    capsys.readouterr()
    assert main(["replay", str(ds), "--from", "2030-01-01"]) == 0
    cap = capsys.readouterr()
    assert cap.out == "" and "rows=0" in cap.err


def test_failing_file_sink_exits_1_and_leaves_nothing(ds, tmp_path, monkeypatch, capsys):
    real = FileSink.write
    calls = {"n": 0}

    def flaky(self, batch):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        real(self, batch)

    monkeypatch.setattr(FileSink, "write", flaky)
    path = tmp_path / "out.jsonl"
    assert main(["replay", str(ds), "--first", "10", "--batch-rows", "3", "--sink", "stdout",
                 "--sink", f"file:{path}"]) == 1
    cap = capsys.readouterr()
    assert len(cap.out.splitlines()) == 10          # the other sink still completed
    assert "disk full" in cap.err
    assert not path.exists() and not (tmp_path / "out.jsonl.tmp").exists()


def test_closed_pipe_is_not_an_error(ds):
    cmd = (f"set -o pipefail; {sys.executable} -m datagen.cli replay {ds} --first 100000 "
           f"| head -1")
    res = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=600, check=False)
    assert res.returncode == 0, res.stderr
    assert "Traceback" not in res.stderr and len(res.stdout.splitlines()) == 1
