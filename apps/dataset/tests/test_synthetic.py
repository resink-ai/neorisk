"""Building and verifying a synthetic dataset, on the tiny project (20 users, 3 days)."""

import json
import shutil

import pyarrow.parquet as pq
import pytest
from conftest import TINY_DESIGNS

from dataset.config import load
from dataset.manifest import files_of
from dataset.names import resolve
from dataset.spider2 import BuildError
from dataset.synthetic import build_synthetic, verify_synthetic

TINY_OBT = TINY_DESIGNS["obt"]


def _root(cfg):
    return resolve(f"{cfg.name}/{cfg.version}")


def _edit(path, old, new):
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))


def test_build_and_verify(tiny_synthetic):
    cfg = load(tiny_synthetic)
    m = build_synthetic(cfg)
    assert m["kind"] == "synthetic" and m["counts"]["questions"] == 1
    meta = json.loads((_root(cfg) / "schema" / "results.json").read_text())
    assert meta["designs"] == {"star": ["star_dim_users", "star_fact_purchase"],
                               "an": ["an_users", "an_users_tier", "an_purchase",
                                      "an_purchase_amount", "an_purchase_by_users"],
                               "obt": ["obt_purchase"]}
    for t, info in meta["tables"].items():
        assert t.startswith(info["design"] + "_")
    assert (_root(cfg) / "expected" / "questions" / "q1.parquet").exists()
    assert (_root(cfg) / "expected" / "labels.parquet").exists()
    assert json.loads((_root(cfg) / "expected" / "check.json").read_text())["failed"] == []
    rep = verify_synthetic(cfg)
    assert rep["ok"], [r for r in rep["tables"] + rep["questions"] if not r.ok]
    assert len(rep["tables"]) == 8
    assert sorted(r.name for r in rep["questions"]) == ["q1/an", "q1/obt", "q1/star"]


def test_build_is_deterministic(tiny_synthetic):
    cfg = load(tiny_synthetic)
    build_synthetic(cfg)
    first = files_of(_root(cfg))
    build_synthetic(cfg)
    assert files_of(_root(cfg)) == first


def test_record_then_rebuild_matches_lock(tiny_synthetic):
    cfg = load(tiny_synthetic)
    build_synthetic(cfg, record=True)
    assert (tiny_synthetic / "v1.lock.json").exists()
    build_synthetic(cfg)
    _edit(tiny_synthetic / "specs" / "an.sql", "SELECT user_id, created_at FROM users;",
          "SELECT user_id, created_at AS born_at FROM users;")
    with pytest.raises(BuildError, match="differs from v1.lock.json"):
        build_synthetic(load(tiny_synthetic))


def test_refuses_unprefixed_table(tiny_synthetic):
    _edit(tiny_synthetic / "specs" / "obt.sql", "-- table: obt_purchase", "-- table: purchase")
    with pytest.raises(BuildError, match="purchase.*obt_"):
        build_synthetic(load(tiny_synthetic))


def test_refuses_hugeint(tiny_synthetic):
    (tiny_synthetic / "specs" / "obt.sql").write_text(
        TINY_OBT + "\n-- table: obt_total\nSELECT sum(amount) AS s FROM purchased;\n")
    with pytest.raises(BuildError, match="obt_total.*s"):
        build_synthetic(load(tiny_synthetic))


def test_simkit_check_mismatch(tiny_synthetic):
    _edit(tiny_synthetic / "dataset.toml", 'purchased_at = "event_time" }',
          'purchased_at = "event_time" }\nwhere = "purchase_id > (SELECT min(purchase_id) '
          'FROM star_fact_purchase)"')
    with pytest.raises(BuildError, match="star_fact_purchase"):
        build_synthetic(load(tiny_synthetic))


def test_star_table_without_check(tiny_synthetic):
    text = (tiny_synthetic / "dataset.toml").read_text()
    (tiny_synthetic / "dataset.toml").write_text(text[:text.rindex("[[check]]")])
    with pytest.raises(BuildError, match="star_fact_purchase"):
        build_synthetic(load(tiny_synthetic))


def test_question_answer_differs(tiny_synthetic):
    cfg = load(tiny_synthetic)
    build_synthetic(cfg)
    _edit(tiny_synthetic / "specs" / "questions" / "q1" / "an.sql", "count(*) AS purchases",
          "count(*) + 1 AS purchases")
    rep = verify_synthetic(cfg)
    assert not rep["ok"]
    assert [r.name for r in rep["questions"] if not r.ok] == ["q1/an"]


def test_answer_cannot_read_other_design(tiny_synthetic):
    (tiny_synthetic / "specs" / "questions" / "q1" / "an.sql").write_text(
        "SELECT tier, count(*) AS purchases, CAST(sum(amount) AS BIGINT) AS revenue "
        "FROM obt_purchase GROUP BY 1;\n")
    with pytest.raises(BuildError, match="q1/an"):
        build_synthetic(load(tiny_synthetic))


def test_oracle_cannot_read_results(tiny_synthetic):
    (tiny_synthetic / "specs" / "questions" / "q1" / "oracle.sql").write_text(
        "SELECT tier, count(*) AS purchases, CAST(sum(amount) AS BIGINT) AS revenue "
        "FROM obt_purchase GROUP BY 1;\n")
    with pytest.raises(BuildError, match="q1.*oracle"):
        build_synthetic(load(tiny_synthetic))


def test_verify_detects_tampered_result(tiny_synthetic):
    cfg = load(tiny_synthetic)
    build_synthetic(cfg)
    f = _root(cfg) / "results" / "an_users.parquet"
    t = pq.read_table(f)
    pq.write_table(t.slice(1), f)
    rep = verify_synthetic(cfg)
    assert [r.name for r in rep["tables"] if not r.ok] == ["an_users"]


def test_failed_build_leaves_no_version(tiny_synthetic):
    cfg = load(tiny_synthetic)
    _edit(tiny_synthetic / "specs" / "obt.sql", "-- table: obt_purchase", "-- table: purchase")
    with pytest.raises(BuildError):
        build_synthetic(cfg)
    assert not _root(cfg).exists()
    shutil.rmtree(_root(cfg).parent, ignore_errors=True)
