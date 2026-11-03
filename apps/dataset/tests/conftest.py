"""The `shop` fixture as a dataset folder, with its data root in tmp_path."""

import importlib.util
from pathlib import Path

import pytest

from dataset.config import load

_spec = importlib.util.spec_from_file_location(
    "refdata_fixtures", Path(__file__).resolve().parents[2] / "refdata" / "tests" / "conftest.py")
shop_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shop_fixtures)

Q1 = "SELECT cid, count(*) AS n, sum(total) AS s FROM orders GROUP BY cid ORDER BY cid;\n"


def make_shop(base: Path, mixed: str = "") -> Path:
    d = base / "datasets" / "shop"
    (d / "specs" / "queries").mkdir(parents=True)
    (d / "dataset.toml").write_text('name = "shop"\nversion = "v1"\nkind = "spider2"\n'
                                    f'[recipe]\n[results.mixed]\n{mixed}')
    (d / "datagen.toml").write_text("[run]\nseed = 1\ndays = 1.0\n")
    (d / "specs" / "pack.py").write_text(shop_fixtures.PACK)
    (d / "specs" / "source.toml").write_text(shop_fixtures.SOURCE)
    (d / "specs" / "ingest.sql").write_text(shop_fixtures.INGEST)
    (d / "specs" / "build.sql").write_text(shop_fixtures.VIEWS)
    (d / "specs" / "queries" / "q1.sql").write_text(Q1)
    return d


@pytest.fixture
def shop_dataset(tmp_path, monkeypatch):
    """(config, source db) for the shop dataset; NEORISK_DATA_ROOT is tmp_path/root."""
    monkeypatch.setenv("NEORISK_DATA_ROOT", str(tmp_path / "root"))
    d = make_shop(tmp_path)
    return load(d), shop_fixtures.make_db(tmp_path / "shop.sqlite")


@pytest.fixture
def shop_cli(tmp_path, monkeypatch):
    """The shop dataset as the only entry of the catalogue; returns the source db."""
    from dataset import config
    monkeypatch.setenv("NEORISK_DATA_ROOT", str(tmp_path / "root"))
    make_shop(tmp_path)
    monkeypatch.setattr(config, "DATASETS", tmp_path / "datasets")
    return shop_fixtures.make_db(tmp_path / "shop.sqlite")


@pytest.fixture
def built(tmp_path, monkeypatch):
    """Build and verify a real dataset into tmp_path; skip when its source is not fetched.
    Returns (manifest, verify report, {event_type: rows} of the log)."""
    import duckdb

    from dataset.names import REPO
    from dataset.spider2 import build_spider2, verify
    from refdata.source import load_source

    def run(name: str):
        monkeypatch.setenv("NEORISK_DATA_ROOT", str(tmp_path / "root"))
        cfg = load(name)
        db = REPO / "data" / "spider2" / load_source(cfg.dir).file
        if not db.exists():
            pytest.skip(f"{db} not fetched (uv run refdata fetch)")
        manifest = build_spider2(cfg, db)
        log = tmp_path / "root" / name / cfg.version / "log" / "*.parquet"
        types = dict(duckdb.sql(f"SELECT event_type, count(*) FROM read_parquet('{log}') "
                                "GROUP BY 1").fetchall())
        return manifest, verify(cfg), types
    return run
