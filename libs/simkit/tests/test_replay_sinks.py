import json

import pyarrow.parquet as pq
import pytest
from conftest import FIXTURES

from neorisk_simkit.io.dataset import run_to_dataset
from neorisk_simkit.io.replay.planner import ReplayRequest, plan_replay
from neorisk_simkit.io.replay.reader import iter_batches
from neorisk_simkit.io.sinks.base import SinkUnavailable, open_sink


@pytest.fixture(scope="module")
def plan(tmp_path_factory):
    r = run_to_dataset(FIXTURES / "mini", "sample", ["behavior.take_p=0.4"],
                       out_dir=tmp_path_factory.mktemp("sk") / "ds")
    return lambda **kw: plan_replay(r.out_dir, ReplayRequest(**kw))


def _drain(p, uri):
    sink, opts = open_sink(uri, numbers=False, doc=p.doc)
    sink.open(p.schema, opts)
    for b in iter_batches(p):
        sink.write(b)
    return sink.close()


def test_json_array_file(plan, tmp_path):
    path = tmp_path / "out.json"
    rep = _drain(plan(first=50), f"file:{path}?format=json-array")
    data = json.loads(path.read_text())
    assert len(data) == 50 == rep.rows and rep.error is None
    assert rep.first_key is not None and rep.last_key >= rep.first_key
    assert not path.with_name("out.json.tmp").exists()


def test_empty_json_array(plan, tmp_path):
    path = tmp_path / "empty.json"
    _drain(plan(types=("took",), t_from=0, t_to=1), f"file:{path}")
    assert json.loads(path.read_text()) == []


def test_empty_selection_every_file_format(plan, tmp_path):
    p = plan(types=("took",), t_from=0, t_to=1)
    rep = _drain(p, f"file:{tmp_path / 'e.jsonl'}")
    assert rep.rows == 0 and rep.first_key is None and (tmp_path / "e.jsonl").read_text() == ""
    _drain(p, f"file:{tmp_path / 'e.csv'}")
    assert (tmp_path / "e.csv").read_text().startswith("event_id,event_type,event_time")
    _drain(p, f"file:{tmp_path / 'e.parquet'}")
    assert pq.read_table(tmp_path / "e.parquet").num_rows == 0


def test_csv_and_parquet_files(plan, tmp_path):
    _drain(plan(first=20), f"file:{tmp_path / 'a.csv'}")
    lines = (tmp_path / "a.csv").read_text().splitlines()
    assert lines[0].startswith("event_id,event_type,event_time") and len(lines) == 21
    _drain(plan(first=20), f"file:{tmp_path / 'a.parquet'}")
    assert pq.read_table(tmp_path / "a.parquet").num_rows == 20


def test_failed_file_sink_leaves_nothing(plan, tmp_path):
    p = plan(first=50)
    path = tmp_path / "bad.jsonl"
    sink, opts = open_sink(f"file:{path}", numbers=False, doc=p.doc)
    sink.open(p.schema, opts)
    sink.write(next(iter_batches(p)))
    sink.abort()
    assert not path.exists() and not path.with_name("bad.jsonl.tmp").exists()


@pytest.mark.parametrize("name", ["m.jsonl", "m.json", "m.csv", "m.parquet"])
def test_midway_failure_leaves_no_file_and_keeps_an_older_one(plan, tmp_path, name):
    p = plan(first=50, batch_rows=10)
    path = tmp_path / name
    path.write_text("previous run")
    sink, opts = open_sink(f"file:{path}", numbers=False, doc=p.doc)
    sink.open(p.schema, opts)
    assert path.with_name(name + ".tmp").exists()
    for i, b in enumerate(iter_batches(p)):
        sink.write(b)
        if i == 1:
            break
    rep = sink.abort("boom")
    assert rep.error == "boom" and rep.rows > 0
    assert not path.with_name(name + ".tmp").exists()
    assert path.read_text() == "previous run"     # an earlier complete file is untouched
    sink.abort()                                  # idempotent


def test_stdout_formats(plan, capsys):
    _drain(plan(first=3), "stdout")
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3 and all(json.loads(x)["event_id"] for x in lines)
    _drain(plan(first=3), "stdout:?format=table")
    assert capsys.readouterr().out.splitlines()[0].split()[:2] == ["event_id", "event_type"]


def test_stdout_table_has_one_header_across_batches(plan, capsys):
    _drain(plan(first=6, batch_rows=2), "stdout:?format=table")
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 7 and sum(x.startswith("event_id") for x in lines) == 1


def test_stdout_broken_pipe_stops_quietly(plan, monkeypatch):
    import os
    import sys

    class Closed:
        def write(self, _):
            raise BrokenPipeError

        def flush(self):
            pass

        def fileno(self):
            raise OSError

    monkeypatch.setattr(sys, "stdout", Closed())
    monkeypatch.setattr(os, "dup2", lambda *a: None)
    rep = _drain(plan(first=10), "stdout")
    assert rep.error is None and rep.rows == 0


def test_unavailable_sinks(plan):
    with pytest.raises(SinkUnavailable, match="kafka sink arrives in M4"):
        open_sink("kafka://localhost:9092/x", numbers=False, doc=plan().doc)
    with pytest.raises(SinkUnavailable, match="unknown sink"):
        open_sink("s3://b/k", numbers=False, doc=plan().doc)
    with pytest.raises(SinkUnavailable, match="cannot infer"):
        open_sink("file:out.dat", numbers=False, doc=plan().doc)
    with pytest.raises(SinkUnavailable, match="does not support"):
        open_sink("stdout:?format=parquet", numbers=False, doc=plan().doc)
