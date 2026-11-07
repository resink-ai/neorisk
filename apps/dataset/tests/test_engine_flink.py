"""The Flink batch engine. The script-level tests need nothing; the runs need the local
cluster up (`apps/dataset/docker/compose.yaml`) and NEORISK_DOCKER=1."""

import json
import os
import shutil
import uuid

import pytest

from dataset import engines
from dataset.config import load
from dataset.engines import flink
from dataset.engines.views import flink_views
from dataset.names import REPO
from dataset.spider2 import build_spider2
from dataset.synthetic import build_synthetic

DOCKER = pytest.mark.skipif(os.environ.get("NEORISK_DOCKER") != "1",
                            reason="needs the local Flink cluster (NEORISK_DOCKER=1)")

SHOP = """-- table: customers
SELECT ext_id AS cid, city FROM customers;
-- table: orders
SELECT p.order_ext AS oid, c.ext_id AS cid,
       DATE_FORMAT(p.event_time, 'M/d/yyyy h:mm:ss a') AS placed,
       DATE_FORMAT(q.event_time, 'yyyy-MM-dd HH:mm:ss') AS paid,
       CAST(p.total AS DOUBLE) / 100.0 AS total, p.note
FROM order_placed p JOIN customers c ON c.customer_id = p.customer_id
LEFT JOIN order_paid q ON q.order_ext = p.order_ext;
"""

TINY = {
    "star": """-- table: star_dim_users
WITH v AS (SELECT user_id, tier, created_at AS valid_from FROM users
           UNION ALL SELECT user_id, tier, event_time FROM tier_changed)
SELECT row_number() OVER (ORDER BY user_id, valid_from) AS users_sk, user_id, tier, valid_from,
       LEAD(valid_from) OVER (PARTITION BY user_id ORDER BY valid_from) AS valid_to,
       LEAD(valid_from) OVER (PARTITION BY user_id ORDER BY valid_from) IS NULL AS is_current
FROM v;

-- table: star_fact_purchase
SELECT p.event_id AS purchase_id, d.users_sk, p.user_id, p.amount, p.event_time AS purchased_at
FROM purchased p JOIN star_dim_users d ON d.user_id = p.user_id
 AND p.event_time >= d.valid_from AND (d.valid_to IS NULL OR p.event_time < d.valid_to);
""",
    "an": """-- table: an_users
SELECT user_id, created_at FROM users;

-- table: an_users_tier
SELECT user_id, tier, created_at AS changed_at FROM users
UNION ALL SELECT user_id, tier, event_time FROM tier_changed;

-- table: an_purchase
SELECT event_id AS purchase_id, event_time AS purchased_at FROM purchased;

-- table: an_purchase_amount
SELECT event_id AS purchase_id, amount, event_time AS changed_at FROM purchased;

-- table: an_purchase_by_users
SELECT event_id AS purchase_id, user_id FROM purchased;
""",
    "obt": """-- table: obt_purchase
SELECT purchase_id, user_id, amount, purchased_at, tier FROM (
  SELECT p.event_id AS purchase_id, p.user_id, p.amount, p.event_time AS purchased_at, t.tier,
         ROW_NUMBER() OVER (PARTITION BY p.event_id ORDER BY t.since DESC) AS rn
  FROM purchased p JOIN (SELECT user_id, tier, created_at AS since FROM users
                         UNION ALL SELECT user_id, tier, event_time FROM tier_changed) t
    ON t.user_id = p.user_id AND t.since <= p.event_time)
WHERE rn = 1;
""",
}


def test_flink_views_cover_every_event(tiny_synthetic):
    cfg = load(tiny_synthetic)
    build_synthetic(cfg)
    from dataset.names import resolve
    schema = json.loads((resolve("tiny/v1") / "schema" / "events.json").read_text())
    views = dict(flink_views(schema))
    assert set(views) == {"users", "purchased", "tier_changed"}
    assert "CAST(entity_key AS BIGINT) AS `user_id`" in views["users"]
    assert "CAST(JSON_VALUE(payload, '$.sim_seq') AS BIGINT) AS seq" in views["purchased"]
    assert "WHERE event_type = 'purchased'" in views["purchased"]


def test_root_cause_takes_the_last_cause():
    trace = ("org.x.SqlGatewayException: wrap\n\tat a.b\nCaused by: org.x.Wrap: mid\n"
             "Caused by: org.apache.calcite.sql.validate.SqlValidatorException: "
             "Column 'nope' not found in any table\n\tat c.d")
    assert flink.root_cause(trace).endswith("Column 'nope' not found in any table")


def test_check_reports_cluster_down(monkeypatch):
    monkeypatch.setattr(flink, "REST", "http://127.0.0.1:9")
    why = flink.Flink().check()
    assert "not running" in why and "docker compose" in why and "up -d" in why


@pytest.fixture
def mounted(monkeypatch):
    """A data root under the one the containers mount, removed afterwards."""
    root = REPO / "data" / "datasets" / "_runs" / "_tests" / uuid.uuid4().hex[:8]
    def use():
        monkeypatch.setenv("NEORISK_DATA_ROOT", str(root))
    yield use
    shutil.rmtree(root, ignore_errors=True)


def _port(cfg, files):
    d = cfg.dir / "engines" / "flink"
    d.mkdir(parents=True)
    for stem, sql in files.items():
        (d / f"{stem}.sql").write_text(sql)


@pytest.fixture
def shop(shop_dataset, mounted):
    cfg, db = shop_dataset
    mounted()
    build_spider2(cfg, db)
    _port(cfg, {"build": SHOP})
    return cfg


@pytest.fixture
def tiny(tiny_synthetic, mounted):
    mounted()
    cfg = load(tiny_synthetic)
    build_synthetic(cfg)
    _port(cfg, TINY)
    return cfg


@DOCKER
def test_check_refuses_unmounted_root(monkeypatch, tmp_path):
    monkeypatch.setenv("NEORISK_DATA_ROOT", str(tmp_path))
    assert "do not mount the data root" in flink.Flink().check()


@DOCKER
def test_flink_run_shop(shop):
    rep = engines.run(shop, "flink")
    assert rep["ok"], [(t["name"], t["detail"], t["missing"][:2], t["extra"][:2])
                       for t in rep["tables"] if not t["ok"]]
    assert rep["peak_rss_mb"] > 500          # the containers are counted


@DOCKER
def test_flink_run_tiny(tiny):
    rep = engines.run(tiny, "flink")
    assert rep["ok"], [(t["name"], t["detail"], t["missing"][:2], t["extra"][:2])
                       for t in rep["tables"] if not t["ok"]]


@DOCKER
def test_flink_block_errors_fail_only_their_tables(shop):
    f = shop.dir / "engines" / "flink" / "build.sql"
    f.write_text(f.read_text().replace("SELECT ext_id AS cid, city FROM customers",
                                       "SELECT ext_id AS cid, city, 1 AS spare FROM customers"))
    t = {t["name"]: t for t in engines.run(shop, "flink")["tables"]}
    assert not t["customers"]["ok"] and "extra ['spare']" in t["customers"]["detail"]
    assert t["orders"]["ok"]


@DOCKER
def test_flink_unknown_column_fails_its_table(shop):
    f = shop.dir / "engines" / "flink" / "build.sql"
    f.write_text(f.read_text().replace("p.note", "p.nope AS note"))
    t = {t["name"]: t for t in engines.run(shop, "flink")["tables"]}
    assert not t["orders"]["ok"] and "nope" in t["orders"]["detail"]
    assert t["customers"]["ok"]
