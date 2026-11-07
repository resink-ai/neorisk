"""Engine runs and the shared grader, on the duckdb engine: the shop (Spider2) and tiny
(synthetic) fixtures."""

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dataset import engines
from dataset.cli import main
from dataset.config import load
from dataset.engines import grade
from dataset.spider2 import build_spider2
from dataset.synthetic import build_synthetic


@pytest.fixture
def shop(shop_dataset):
    cfg, db = shop_dataset
    build_spider2(cfg, db)
    return cfg


@pytest.fixture
def tiny(tiny_synthetic):
    cfg = load(tiny_synthetic)
    build_synthetic(cfg)
    return cfg


def _by_name(rep):
    return {t["name"]: t for t in rep["tables"]}


def test_duckdb_run_passes_spider2(shop):
    rep = engines.run(shop, "duckdb")
    assert rep["ok"], rep["tables"]
    assert set(_by_name(rep)) == {"customers", "orders"}
    out = engines.runs_dir(shop, "duckdb") / rep["run_id"]
    assert json.loads((out / "run.json").read_text())["ok"]
    assert rep["events"] > 0 and rep["events_per_s"] > 0 and rep["peak_rss_mb"] > 0
    assert rep["timings"]["build"] >= 0


def test_duckdb_run_passes_synthetic(tiny):
    rep = engines.run(tiny, "duckdb")
    assert rep["ok"], [t for t in rep["tables"] if not t["ok"]]
    assert len(rep["tables"]) == 8


def test_missing_block_fails_that_table_only(shop, monkeypatch):
    real = engines.port_blocks

    def without_orders(cfg, engine):
        b = real(cfg, engine)
        del b["build"]["orders"]
        return b
    monkeypatch.setattr(engines, "port_blocks", without_orders)
    t = _by_name(engines.run(shop, "duckdb"))
    assert t["customers"]["ok"]
    assert not t["orders"]["ok"] and "no port block" in t["orders"]["detail"]


def test_block_error_fails_that_table_only(tiny, monkeypatch):
    real = engines.port_blocks

    def broken(cfg, engine):
        b = real(cfg, engine)
        b["an"]["an_users"] = "SELECT nope FROM users"
        return b
    monkeypatch.setattr(engines, "port_blocks", broken)
    t = _by_name(engines.run(tiny, "duckdb"))
    assert not t["an_users"]["ok"] and "nope" in t["an_users"]["detail"]
    assert t["an_purchase"]["ok"] and t["obt_purchase"]["ok"]


def test_extra_block_is_reported(shop, monkeypatch):
    real = engines.port_blocks

    def extra(cfg, engine):
        b = real(cfg, engine)
        b["build"]["ghost"] = "SELECT 1 AS x"
        return b
    monkeypatch.setattr(engines, "port_blocks", extra)
    rep = engines.run(shop, "duckdb")
    assert not rep["ok"] and "ghost" in _by_name(rep)["build"]["detail"]


def test_wrong_columns_fail_with_difference(shop, monkeypatch):
    real = engines.port_blocks

    def renamed(cfg, engine):
        b = real(cfg, engine)
        b["build"]["customers"] = "SELECT ext_id AS customer, city FROM customers"
        return b
    monkeypatch.setattr(engines, "port_blocks", renamed)
    t = _by_name(engines.run(shop, "duckdb"))["customers"]
    assert not t["ok"] and "customer" in t["detail"] and "cid" in t["detail"]


def _out(tmp_path, table):
    d = tmp_path / "tables" / "x"
    d.mkdir(parents=True)
    pq.write_table(table, d / "part-0.parquet")
    return d


def test_naive_timestamp_graded_as_utc(tmp_path):
    want = pa.table({"at": pa.array([0, 3_600_000_000], pa.timestamp("us", "UTC")),
                     "n": pa.array([1, 2], pa.int64())})
    got = pa.table({"at": pa.array([0, 3_600_000_000_000], pa.timestamp("ns")),
                    "n": pa.array([1, 2], pa.int32())})
    assert grade.typed("x", want, _out(tmp_path, got)).ok


def test_decimal_and_widths_graded_by_value(tmp_path):
    want = pa.table({"s": pa.array([10, 20], pa.int64()), "f": pa.array([0.5, 1.0])})
    got = pa.table({"s": pa.array([10, 20], pa.decimal128(38, 0)),
                    "f": pa.array([0.5, 1.0], pa.float32())})
    assert grade.typed("x", want, _out(tmp_path, got)).ok


def test_lossy_cast_fails(tmp_path):
    want = pa.table({"n": pa.array([1, 2], pa.int64())})
    got = pa.table({"n": pa.array(["1", "2"])})
    r = grade.typed("x", want, _out(tmp_path, got))
    assert not r.ok and "n" in r.detail and "string" in r.detail


def test_fractional_float_into_int_fails(tmp_path):
    want = pa.table({"n": pa.array([1, 2], pa.int64())})
    got = pa.table({"n": pa.array([1.5, 2.0])})
    assert not grade.typed("x", want, _out(tmp_path, got)).ok


def test_interrupted_run_has_no_run_json(shop, monkeypatch):
    from dataset.engines import duck

    def boom(self, job):
        raise KeyboardInterrupt
    monkeypatch.setattr(duck.DuckDB, "build", boom)
    with pytest.raises(KeyboardInterrupt):
        engines.run(shop, "duckdb")
    d = engines.runs_dir(shop, "duckdb")
    assert not list(d.glob("*/run.json"))
    assert engines.latest_runs(shop) == {}


def test_engine_not_ready_writes_nothing(shop, monkeypatch):
    from dataset.engines import duck
    monkeypatch.setattr(duck.DuckDB, "check", lambda self: "start it: make up")
    with pytest.raises(engines.EngineNotReady, match="make up"):
        engines.run(shop, "duckdb")
    assert not engines.runs_dir(shop, "duckdb").exists()


def test_cli_run_and_list_engines(shop_cli, capsys):
    assert main(["build", "shop", "--db", str(shop_cli)]) == 0
    assert main(["run", "shop", "--engine", "duckdb"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] and out["engine"] == "duckdb" and out["failed"] == []
    assert main(["list", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["engines"] == ["duckdb"]


def test_cli_run_unknown_engine(shop_cli, capsys):
    with pytest.raises(SystemExit):
        main(["run", "shop", "--engine", "presto"])


def test_cli_run_not_built(shop_cli, capsys):
    assert main(["run", "shop", "--engine", "duckdb"]) == 2
    assert "not built" in capsys.readouterr().err
