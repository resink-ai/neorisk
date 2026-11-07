"""The Spark engine on the shop (Spider2) and tiny (synthetic) fixtures. One local Spark
session serves the module; it skips without pyspark."""

import json

import duckdb
import pyarrow.parquet as pq
import pytest

pytest.importorskip("pyspark")

from dataset import engines
from dataset.config import load
from dataset.engines import grade
from dataset.engines.spark import session
from dataset.engines.views import spark_views
from dataset.names import resolve
from dataset.spider2 import build_spider2
from dataset.synthetic import build_synthetic
from refdata.logviews import attach_log

SHOP = """-- table: customers
SELECT ext_id AS cid, city FROM customers;
-- table: orders
SELECT p.order_ext AS oid, c.ext_id AS cid,
       date_format(p.event_time, 'M/d/yyyy h:mm:ss a') AS placed,
       date_format(q.event_time, 'yyyy-MM-dd HH:mm:ss') AS paid,
       p.total / 100.0 AS total, p.note
FROM order_placed p JOIN customers c USING (customer_id)
LEFT JOIN order_paid q ON q.order_ext = p.order_ext;
"""

TINY_OBT = """-- table: obt_purchase
WITH t AS (SELECT user_id, tier, created_at AS at FROM users
           UNION ALL SELECT user_id, tier, event_time FROM tier_changed),
m AS (SELECT p.event_id, p.user_id, p.amount, p.event_time, t.tier,
             row_number() OVER (PARTITION BY p.event_id ORDER BY t.at DESC) AS rn
      FROM purchased p JOIN t ON t.user_id = p.user_id AND t.at <= p.event_time)
SELECT event_id AS purchase_id, user_id, amount, event_time AS purchased_at, tier
FROM m WHERE rn = 1;
"""


@pytest.fixture(scope="module", autouse=True)
def spark():
    s = session()
    yield s
    s.stop()


def _port(cfg, files):
    d = cfg.dir / "engines" / "spark"
    d.mkdir(parents=True)
    for stem, sql in files.items():
        (d / f"{stem}.sql").write_text(sql)


@pytest.fixture
def shop(shop_dataset):
    cfg, db = shop_dataset
    build_spider2(cfg, db)
    _port(cfg, {"build": SHOP})
    return cfg


@pytest.fixture
def tiny(tiny_synthetic):
    from conftest import TINY_DESIGNS
    cfg = load(tiny_synthetic)
    build_synthetic(cfg)
    _port(cfg, {"star": TINY_DESIGNS["star"], "an": TINY_DESIGNS["an"], "obt": TINY_OBT})
    return cfg


def test_spark_views_match_duckdb(tiny, spark, tmp_path):
    root = resolve(f"{tiny.name}/{tiny.version}")
    schema = json.loads((root / "schema" / "events.json").read_text())
    spark.read.parquet(str(root / "log")).createOrReplaceTempView("log")
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    attach_log(con, root)
    for name, sql in spark_views(schema):
        out = tmp_path / name
        spark.sql(sql).coalesce(1).write.parquet(str(out))
        want = con.sql(f'SELECT * FROM "{name}"').arrow().read_all()
        r = grade.typed(name, want, out)
        assert r.ok, (name, r.detail, r.missing, r.extra)
        assert pq.read_table(out).column_names == want.column_names


def test_spark_run_shop(shop):
    rep = engines.run(shop, "spark")
    assert rep["ok"], [(t["name"], t["detail"], t["missing"][:2], t["extra"][:2])
                       for t in rep["tables"] if not t["ok"]]
    assert rep["peak_rss_mb"] > 200          # the JVM is counted


def test_spark_run_tiny(tiny):
    rep = engines.run(tiny, "spark")
    assert rep["ok"], [(t["name"], t["detail"], t["missing"][:2], t["extra"][:2])
                       for t in rep["tables"] if not t["ok"]]


def test_spark_block_error_fails_table(shop):
    f = shop.dir / "engines" / "spark" / "build.sql"
    f.write_text(f.read_text().replace("SELECT ext_id AS cid, city FROM customers",
                                       "SELECT ext_id AS cid, city FROM nowhere"))
    t = {t["name"]: t for t in engines.run(shop, "spark")["tables"]}
    assert not t["customers"]["ok"] and "nowhere" in t["customers"]["detail"]
    assert t["orders"]["ok"]
