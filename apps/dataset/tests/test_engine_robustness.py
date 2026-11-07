"""Failure paths of the Flink engines that need no cluster: timeouts, leaked topics, stray
port blocks and the not-ready message."""

import json
from types import SimpleNamespace

import pyarrow as pa
import pytest

from dataset import bench
from dataset.engines import Job, flink, stream


def _job(tmp_path, blocks, columns):
    (tmp_path / "schema").mkdir()
    (tmp_path / "schema" / "events.json").write_text(json.dumps({"events": []}))
    cfg = SimpleNamespace(name="shop", version="v1", kind="spider2")
    return Job(cfg, tmp_path, tmp_path / "run1", blocks, columns, 0)


class FakeGateway:
    statements: list = []

    def __init__(self, *a, **k):
        pass

    def run(self, statement, timeout=120):
        FakeGateway.statements.append(statement)
        return []

    def close(self):
        pass


def test_bench_timeout_outlasts_the_flink_job_timeout():
    # the child must live long enough for wait_job to cancel its job on the cluster
    assert bench.RUN_TIMEOUT >= flink.JOB_TIMEOUT + 300


def test_flink_skips_blocks_for_tables_not_in_the_results(tmp_path, monkeypatch):
    monkeypatch.setattr(flink, "Gateway", FakeGateway)
    job = _job(tmp_path, {"build": {"ghost": "SELECT 1 AS x"}}, {"t": [("x", pa.int64())]})
    built = flink.Flink().build(job)             # graded later as "blocks not in the results"
    assert built.errors == {}
    assert not any("ghost" in s for s in FakeGateway.statements)


def test_stream_deletes_its_topics_when_the_replay_fails(tmp_path, monkeypatch):
    deleted = []
    monkeypatch.setattr(stream, "delete_topics", lambda names: deleted.extend(names))
    monkeypatch.setattr(stream, "create_topic", lambda name: None)

    def broken(root, topic):
        raise RuntimeError("broker gone")
    monkeypatch.setattr(stream, "replay_log", broken)
    job = _job(tmp_path, {"build": {"t": "SELECT 1 AS x"}}, {"t": [("x", pa.int64())]})
    with pytest.raises(RuntimeError, match="broker gone"):
        stream.FlinkStream().build(job)
    assert "shop-v1-run1-log" in deleted and "shop-v1-run1-t" in deleted


def test_stream_deletes_its_topics_when_the_log_cannot_be_read(tmp_path, monkeypatch):
    deleted = []
    monkeypatch.setattr(stream, "delete_topics", lambda names: deleted.extend(names))
    monkeypatch.setattr(stream, "create_topic", lambda name: None)
    monkeypatch.setattr(stream, "replay_log", lambda root, topic: 0)

    class NoLog(FakeGateway):
        def run(self, statement, timeout=120):
            raise flink.FlinkError("no such topic")
    monkeypatch.setattr(flink, "Gateway", NoLog)
    job = _job(tmp_path, {"build": {"t": "SELECT 1 AS x"}}, {"t": [("x", pa.int64())]})
    built = stream.FlinkStream().build(job)
    assert "cannot be read" in built.errors["t"]
    assert "shop-v1-run1-log" in deleted


def test_stream_not_ready_names_the_start_command(monkeypatch):
    monkeypatch.setattr(flink.Flink, "check", lambda self: None)

    def down():
        raise OSError("refused")
    monkeypatch.setattr(stream, "_admin", down)
    why = stream.FlinkStream().check()
    assert "Redpanda" in why and "docker compose" in why and "up -d" in why
