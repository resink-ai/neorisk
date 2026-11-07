"""The Flink streaming engine: the changelog fold needs nothing; the runs need the local
cluster and Redpanda up and NEORISK_DOCKER=1."""

import datetime as dt
import os
import shutil
import uuid
from pathlib import Path

import pyarrow as pa
import pytest

from dataset.engines.stream import FoldError, fold

DOCKER = pytest.mark.skipif(os.environ.get("NEORISK_DOCKER") != "1",
                            reason="needs the local Flink cluster and Redpanda (NEORISK_DOCKER=1)")

COLS = [("name", pa.string()), ("n", pa.int64())]


def _c(**row):
    return {"before": None, "after": row, "op": "c"}


def _d(**row):
    return {"before": row, "after": None, "op": "d"}


def test_fold_inserts_and_retractions():
    msgs = [_c(name="a", n=1), _d(name="a", n=1), _c(name="a", n=2), _c(name="b", n=1),
            _c(name="b", n=1), _d(name="b", n=1), None]
    t = fold(msgs, COLS)
    assert t.schema == pa.schema(COLS)
    assert sorted(t.to_pylist(), key=lambda r: r["name"]) == [{"name": "a", "n": 2},
                                                             {"name": "b", "n": 1}]


def test_fold_keeps_duplicates():
    t = fold([_c(name="a", n=1), _c(name="a", n=1)], COLS)
    assert t.num_rows == 2


def test_fold_order_does_not_matter():
    msgs = [_d(name="a", n=1), _c(name="a", n=1), _c(name="a", n=2)]
    assert fold(msgs, COLS).to_pylist() == [{"name": "a", "n": 2}]


def test_fold_rejects_unmatched_delete():
    with pytest.raises(FoldError, match="does not fold"):
        fold([_c(name="a", n=1), _d(name="z", n=9)], COLS)


def test_fold_update_op():
    msgs = [_c(name="a", n=1), {"before": {"name": "a", "n": 1},
                                "after": {"name": "a", "n": 3}, "op": "u"}]
    assert fold(msgs, COLS).to_pylist() == [{"name": "a", "n": 3}]


def test_fold_types():
    cols = [("at", pa.timestamp("us", "UTC")), ("day", pa.date32()), ("x", pa.float64()),
            ("ok", pa.bool_()), ("k", pa.int32())]
    t = fold([_c(at="2021-01-01 18:05:02.5", day="2021-01-02", x=1, ok=True, k=3),
              _c(at="2021-01-01 18:05:02Z", day=None, x=None, ok=None, k=None)], cols)
    assert t.schema == pa.schema(cols)
    rows = t.to_pylist()
    assert rows[0]["at"] == dt.datetime(2021, 1, 1, 18, 5, 2, 500000, tzinfo=dt.UTC)
    assert rows[0]["day"] == dt.date(2021, 1, 2) and rows[0]["x"] == 1.0
    assert rows[1]["at"] == dt.datetime(2021, 1, 1, 18, 5, 2, tzinfo=dt.UTC)


def test_message_value():
    from dataset.engines.stream import message_values
    t = pa.table({"seq": pa.array([1], pa.int64()),
                  "event_time": pa.array([dt.datetime(2021, 1, 1, 18, 5, 2, 7,
                                                      tzinfo=dt.UTC)], pa.timestamp("us", "UTC")),
                  "event_type": ["x_created"], "entity_type": ["x"], "entity_key": ["5"],
                  "schema_version": pa.array([1], pa.int32()), "payload": ['{"a":"1"}']})
    [(key, value)] = list(message_values(t))
    assert key == b"5"
    assert value == (b'{"seq": 1, "event_time": "2021-01-01 18:05:02.000007Z", "event_type": '
                     b'"x_created", "entity_type": "x", "entity_key": "5", "schema_version": 1, '
                     b'"payload": "{\\"a\\":\\"1\\"}"}')


@pytest.fixture
def tiny(tiny_synthetic, monkeypatch):
    from test_engine_flink import TINY

    from dataset.config import load
    from dataset.synthetic import build_synthetic
    repo = Path(__file__).resolve().parents[3]       # dataset.names.REPO is patched here
    root = repo / "data" / "datasets" / "_runs" / "_tests" / uuid.uuid4().hex[:8]
    monkeypatch.setenv("NEORISK_DATA_ROOT", str(root))
    cfg = load(tiny_synthetic)
    build_synthetic(cfg)
    d = cfg.dir / "engines" / "flink"
    d.mkdir(parents=True)
    for stem, sql in TINY.items():
        (d / f"{stem}.sql").write_text(sql)
    yield cfg
    shutil.rmtree(root, ignore_errors=True)


@DOCKER
def test_stream_run_tiny(tiny):
    from dataset import engines
    rep = engines.run(tiny, "flink-stream")
    failed = {t["name"]: t["detail"] for t in rep["tables"] if not t["ok"]}
    # the batch port's OVER windows (ROW_NUMBER, LEAD over a non-time order) do not plan in
    # streaming mode; that table and the fact that reads it fail with the planner's reason,
    # the other six pass
    assert sorted(failed) == ["star_dim_users", "star_fact_purchase"], failed
    assert all("OVER window" in d for d in failed.values())
    assert rep["timings"]["load"] > 0 and rep["timings"]["write"] is not None
