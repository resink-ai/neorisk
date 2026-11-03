import sqlite3

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dataset.config import load
from dataset.names import resolve
from dataset.spider2 import BuildError, build_spider2, verify


def test_build_then_verify_ok(shop_dataset):
    cfg, db = shop_dataset
    m = build_spider2(cfg, db)
    root = resolve("shop/v1")
    for f in ("manifest.json", "schema/events.json", "schema/results.json",
              "log/part-00000.parquet", "results/customers.parquet", "results/orders.parquet",
              "expected/queries/q1.parquet"):
        assert (root / f).exists(), f
    assert m["counts"] == {"log": 7, "results/customers": 2, "results/orders": 3, "queries": 1}
    rep = verify(cfg)
    assert rep["ok"], rep
    assert [t.name for t in rep["tables"]] == ["customers", "orders"]
    assert [q.name for q in rep["queries"]] == ["q1"]


def test_verify_catches_changed_results(shop_dataset):
    cfg, db = shop_dataset
    build_spider2(cfg, db)
    p = resolve("shop/v1/results/orders.parquet")
    t = pq.read_table(p)
    city = t.column("note").to_pylist()
    city[0] = "changed"
    pq.write_table(t.set_column(t.schema.get_field_index("note"), "note",
                                pa.array(city, pa.string())), p)
    rep = verify(cfg)
    assert not rep["ok"]
    assert [r.name for r in rep["tables"] if not r.ok] == ["orders"]


def test_verify_reads_no_source(shop_dataset):
    cfg, db = shop_dataset
    build_spider2(cfg, db)
    db.unlink()
    assert verify(cfg)["ok"]


def test_mixed_declaration_must_match(shop_dataset, tmp_path):
    cfg, db = shop_dataset
    (cfg.dir / "dataset.toml").write_text(
        (cfg.dir / "dataset.toml").read_text() + 'orders = ["note"]\n')
    with pytest.raises(BuildError, match="orders"):
        build_spider2(load(cfg.dir), db)


def test_build_is_deterministic(shop_dataset):
    cfg, db = shop_dataset
    assert build_spider2(cfg, db)["files"] == build_spider2(cfg, db)["files"]


def test_lock_record_and_mismatch(shop_dataset):
    cfg, db = shop_dataset
    build_spider2(cfg, db, record=True)
    assert (cfg.dir / "v1.lock.json").exists()
    build_spider2(cfg, db)                                     # same output: accepted
    con = sqlite3.connect(db)
    con.execute("UPDATE orders SET note = 'zz' WHERE oid = 'o1'")
    con.commit()
    con.close()
    with pytest.raises(BuildError, match=r"results/orders\.parquet"):
        build_spider2(cfg, db)
    assert verify(cfg)["ok"]                                   # the recorded build is intact
