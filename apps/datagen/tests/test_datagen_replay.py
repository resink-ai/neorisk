"""datagen replay: canonical order, selection, sinks, pacing, resume and late labels (P4 exit)."""

import io
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from datagen.cli import main
from neorisk_simkit.io import read
from neorisk_simkit.replay import Pacing, Selection, replay, select
from neorisk_simkit.replay.sinks import KafkaSink, StdoutSink

PAY = Path(__file__).resolve().parents[3] / "examples" / "payments"


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    proj = tmp_path_factory.mktemp("rp") / "payments"
    shutil.copytree(PAY, proj, ignore=shutil.ignore_patterns("out", "reports", "__pycache__"))
    assert main(["run", str(proj), "--set", "customers=120", "--set", "run.days=60",
                 "--set", "fraud_p=0.05"]) == 0
    return proj / "out" / "default-s7"


def _lines(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines()]


def test_full_replay_is_the_canonical_order(run_dir, tmp_path):
    out = tmp_path / "all.jsonl"
    assert main(["replay", str(run_dir), "--sink", f"file:{out}"]) == 0
    rows = _lines(out)
    run = read(run_dir)
    assert len(rows) == sum(df.height for df in run.events.values())
    seqs = [int(r["seq"]) for r in rows]
    assert seqs == sorted(seqs)
    r = next(x for x in rows if x["event_type"] == "payment_captured")
    assert isinstance(r["event_id"], str) and isinstance(r["amount"], str)
    assert r["event_time"].endswith("Z") and "lamport" not in r
    assert set(r) == {c["name"] for t in run.schema["tables"] if t["name"] == "payment_captured"
                      for c in t["columns"]}


def test_selection_options(run_dir):
    run = read(run_dir)
    assert select(run, Selection(first=10))["seq"].to_list() == sorted(
        select(run, Selection())["seq"].to_list())[:10]
    last = select(run, Selection(last=5))
    assert last.height == 5 and last["seq"].is_sorted()
    big = select(run, Selection(types=["payment_captured"], where="amount>=10000"))
    assert big.height and (big["amount"] >= 10000).all()
    assert set(big["event_type"]) == {"payment_captured"}
    t0 = datetime(2026, 1, 10, tzinfo=UTC)
    t1 = datetime(2026, 1, 11, tzinfo=UTC)
    day = select(run, Selection(start=t0, end=t1))
    assert day.height and day["event_time"].min() >= t0 and day["event_time"].max() < t1
    with pytest.raises(ValueError):
        select(run, Selection(where="amount >> 3"))


def test_owner_sampling_keeps_whole_histories(run_dir):
    run = read(run_dir)
    some = select(run, Selection(owners=0.1))
    allr = select(run, Selection())
    pids = set(some["partition_id"].drop_nulls())
    assert 0 < len(pids) < allr["partition_id"].n_unique()
    full = allr.filter(pl.col("partition_id").is_in(list(pids)))
    assert full.height == some.height


def test_late_labels_appear_in_the_stream_when_they_become_available(run_dir, tmp_path):
    out = tmp_path / "with_labels.jsonl"
    assert main(["replay", str(run_dir), "--with-labels", "--sink", f"file:{out}"]) == 0
    rows = _lines(out)
    labels = [(i, r) for i, r in enumerate(rows) if r["event_type"] == "label_available"]
    assert labels
    times = [r["event_time"] for r in rows]
    assert times == sorted(times)
    auth = {r["payment_id"]: i for i, r in enumerate(rows)
            if r["event_type"] == "payment_authorized"}
    disputes = {r["payment_id"]: (i, r["event_time"]) for i, r in enumerate(rows)
                if r["event_type"] == "dispute_opened" and r["reason"] == "fraud"}
    seen = 0
    for i, lab in labels:
        pid = lab["target_id"]
        assert auth[pid] < i                                    # long after the payment
        if pid in disputes:
            j, t = disputes[pid]
            assert lab["event_time"] == t and j < i               # with its dispute
            seen += 1
    assert seen > 0
    assert main(["replay", str(run_dir), "--sink", f"file:{tmp_path / 'x.jsonl'}"]) == 0
    assert not any(r["event_type"] == "label_available" for r in _lines(tmp_path / "x.jsonl"))


def test_file_formats_and_resume(run_dir, tmp_path):
    arr, pq = tmp_path / "a.json", tmp_path / "a.parquet"
    assert main(["replay", str(run_dir), "--first", "50", "--sink", f"file:{arr}?format=json-array",
                 "--sink", f"file:{pq}?format=parquet"]) == 0
    assert len(json.loads(arr.read_text())) == 50 and pl.read_parquet(pq).height == 50
    part = tmp_path / "p.jsonl"
    assert main(["replay", str(run_dir), "--first", "300", "--sink", f"file:{part}"]) == 0
    first = _lines(part)
    assert main(["replay", str(run_dir), "--resume", "--sink", f"file:{part}"]) == 0
    rest = _lines(part)
    whole = tmp_path / "w.jsonl"
    assert main(["replay", str(run_dir), "--sink", f"file:{whole}"]) == 0
    assert first + rest == _lines(whole)


def test_kafka_sink_with_a_fake_producer(run_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                      # the sink's resume state lands here
    class Fake:
        def __init__(self):
            self.msgs = []

        def produce(self, topic, value, key, headers):
            self.msgs.append((topic, json.loads(value), key, dict(headers)))

        def flush(self):
            pass
    fake = Fake()
    sink = KafkaSink("localhost:9092", "pay.{event_type}", key="payment_id", producer=fake)
    rep = replay(read(run_dir), Selection(types=["payment_captured", "refund_issued"]), [sink])
    assert rep["ok"] and rep["sinks"][0]["sent"] == len(fake.msgs) > 0
    topic, msg, key, headers = fake.msgs[0]
    assert topic == f"pay.{msg['event_type']}" and key == msg["payment_id"].encode()
    assert headers["event_type"] == msg["event_type"].encode()


def test_pacing_rebase_dry_run_and_closed_pipes(run_dir, capsys):
    slept = []
    now = datetime(2030, 5, 1, tzinfo=UTC)
    buf = io.StringIO()
    rep = replay(read(run_dir), Selection(first=200),
                 [StdoutSink(stream=buf)],
                 Pacing("x3600", rebase=True, sleep=slept.append, clock=lambda: now))
    rows = [json.loads(x) for x in buf.getvalue().splitlines()]
    assert rows[0]["event_time"] == "2030-05-01T00:00:00.000000Z"
    span = (datetime.fromisoformat(rows[-1]["event_time"]) - now)
    assert sum(slept) == pytest.approx(span.total_seconds() / 3600, rel=1e-6)
    assert rep["ok"]

    class Closed(io.StringIO):
        def write(self, s):
            raise BrokenPipeError
    rep = replay(read(run_dir), Selection(first=10), [StdoutSink(stream=Closed())])
    assert rep["ok"]
    assert main(["replay", str(run_dir), "--dry-run", "--types", "payment_captured",
                 "--pace", "x60"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["rows"] > 0 and plan["duration_s"] > 0
    assert main(["replay", str(run_dir), "--first", "1", "--last", "1"]) == 2
    assert main(["replay", str(run_dir), "--sink", "ftp://x"]) == 2


def test_kafka_without_the_extra_explains_itself(run_dir, capsys):
    pytest.importorskip("polars")
    try:
        import confluent_kafka  # noqa: F401
        pytest.skip("confluent-kafka is installed")
    except ImportError:
        pass
    assert main(["replay", str(run_dir), "--first", "1",
                 "--sink", "kafka://localhost:9092/t"]) == 1
    assert "confluent-kafka" in capsys.readouterr().err
