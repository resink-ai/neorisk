"""`dataset bench`: every requested engine on every requested dataset, one report. The
engines here are DuckDB and stand-ins built on it."""

import json
import re
import shutil

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dataset import engines
from dataset.bench import bench
from dataset.cli import main
from dataset.config import load
from dataset.engines.duck import DuckDB
from dataset.spider2 import build_spider2
from dataset.synthetic import build_synthetic


class OffByOne(DuckDB):
    """DuckDB, then the first customer's city changed: wrong the same way on every engine."""

    def build(self, job):
        built = super().build(job)
        f = job.table_dir("customers") / "part-0.parquet"
        t = pq.read_table(f)
        city = t["city"].to_pylist()
        pq.write_table(t.set_column(1, "city", pa.array(["Oslo", *city[1:]])), f)
        return built


class Down(DuckDB):
    def check(self):
        return "the cluster is not running; start it"


@pytest.fixture
def two(tmp_path, monkeypatch):
    """shop (Spider2) and tiny (synthetic), both built, as the whole catalogue."""
    from conftest import make_shop, make_tiny, shop_fixtures

    from dataset import config, names
    monkeypatch.setenv("NEORISK_DATA_ROOT", str(tmp_path / "root"))
    monkeypatch.setattr(names, "REPO", tmp_path)
    monkeypatch.setattr(config, "DATASETS", tmp_path / "datasets")
    shop = load(make_shop(tmp_path))
    build_spider2(shop, shop_fixtures.make_db(tmp_path / "shop.sqlite"))
    tiny = load(make_tiny(tmp_path))
    build_synthetic(tiny)
    return shop, tiny


def _port(cfg, engine_dir):
    d = cfg.dir / "engines" / engine_dir
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(cfg.dir / "specs" / "build.sql", d / "build.sql")


def _fake(monkeypatch, **by_name):
    real = engines.engine
    monkeypatch.setattr(engines, "engine",
                        lambda n: by_name[n]() if n in by_name else real(n))


def test_bench_duckdb_two_datasets(two):
    path = bench(["shop", "tiny"], ["duckdb"], isolate=False)
    rep = json.loads((path / "report.json").read_text())
    assert [(r["name"], r["engine"], r["status"]) for r in rep["runs"]] == [
        ("shop", "duckdb", "pass"), ("tiny", "duckdb", "pass")]
    for r in rep["runs"]:
        assert r["wall_s"] >= 0 and r["peak_rss_mb"] > 0 and r["events_per_s"] > 0
        assert set(r["timings"]) == {"load", "plan", "build", "write"}
    assert rep["ok"]


def test_bench_engine_without_port_is_not_ported(two):
    rep = json.loads((bench(["tiny"], ["duckdb", "spark"], isolate=False) / "report.json").read_text())
    assert [r["status"] for r in rep["runs"]] == ["pass", "not ported"]
    assert rep["ok"]


def test_bench_skips_engine_not_ready(two, monkeypatch):
    shop, _ = two
    _port(shop, "flink")
    _fake(monkeypatch, flink=Down)
    rep = json.loads((bench(["shop"], ["flink", "duckdb"], isolate=False) / "report.json").read_text())
    by = {r["engine"]: r for r in rep["runs"]}
    assert by["flink"]["status"] == "not run" and "not running" in by["flink"]["reason"]
    assert by["duckdb"]["status"] == "pass"
    assert not rep["ok"]


def test_bench_cross_engine_agreement(two, monkeypatch):
    shop, _ = two
    _port(shop, "spark")
    _port(shop, "flink")
    _fake(monkeypatch, spark=OffByOne, flink=OffByOne)
    rep = json.loads((bench(["shop"], ["duckdb", "spark", "flink"], isolate=False) / "report.json")
                     .read_text())
    by = {r["engine"]: r for r in rep["runs"]}
    assert by["spark"]["status"] == "fail" and by["spark"]["failed"][0]["name"] == "customers"
    agree = rep["agreement"]["shop"]["customers"]
    assert agree == {"duckdb": [], "spark": ["flink"], "flink": ["spark"]}
    assert "orders" not in rep["agreement"]["shop"]


def test_bench_isolated_runs_in_their_own_process(two, monkeypatch):
    # each run is a `dataset run` subprocess, so its peak memory is its own, not what an
    # earlier run (a Spark JVM, DuckDB's heap) left in the bench process
    def no(*a, **k):
        raise AssertionError("ran in the bench process")
    monkeypatch.setattr(engines, "run", no)
    rep = json.loads((bench(["shop", "tiny"], ["duckdb"]) / "report.json").read_text())
    assert [r["status"] for r in rep["runs"]] == ["pass", "pass"]
    assert all(r["peak_rss_mb"] > 0 for r in rep["runs"])


def test_report_html_is_self_contained(two):
    html = (bench(["shop"], ["duckdb"], isolate=False) / "report.html").read_text()
    assert "<table" in html and "shop" in html and "duckdb" in html
    assert not re.search(r"""(src|href)=["']?https?://""", html)


def test_cli_bench(two, capsys):
    assert main(["bench", "shop", "tiny", "--engines", "duckdb"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] and out["report"].endswith("report.html")


def test_cli_bench_unknown_engine(two, capsys):
    assert main(["bench", "shop", "--engines", "duckdb,presto"]) == 2
    assert "presto" in capsys.readouterr().err
