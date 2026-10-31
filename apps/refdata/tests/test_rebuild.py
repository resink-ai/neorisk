import sqlite3

import pytest

from refdata import cli
from refdata.ingest import ingest
from refdata.rebuild import rebuild


def _rows(db, sql):
    con = sqlite3.connect(db)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def _built(shop, tmp_path):
    proj, db = shop
    ds = ingest(proj, db, tmp_path / "ds")
    return proj, db, ds, rebuild(ds, proj, db, tmp_path / "rebuilt.sqlite")


def test_rebuild_tables_and_ddl(shop, tmp_path):
    _, db, _, out = _built(shop, tmp_path)
    q = "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
    assert _rows(out, q) == _rows(db, q)
    assert _rows(out, "SELECT count(*) FROM customers") == [(2,)]
    assert _rows(out, "SELECT count(*) FROM orders") == [(3,)]


def test_view_formats_time_back(shop, tmp_path):
    _, db, _, out = _built(shop, tmp_path)
    q = "SELECT oid, placed, paid, total, note FROM orders ORDER BY oid"
    assert _rows(out, q) == _rows(db, q)


def test_missing_column_named(shop, tmp_path):
    proj, db = shop
    ds = ingest(proj, db, tmp_path / "ds")
    views = (proj / "specs" / "views.sql").read_text()
    (proj / "specs" / "views.sql").write_text(views.replace(", p.note", ""))
    with pytest.raises(ValueError, match="note"):
        rebuild(ds, proj, db, tmp_path / "rebuilt.sqlite")


def test_missing_table_block_named(shop, tmp_path):
    proj, db = shop
    ds = ingest(proj, db, tmp_path / "ds")
    views = (proj / "specs" / "views.sql").read_text()
    (proj / "specs" / "views.sql").write_text(views.split("-- table: orders")[0])
    with pytest.raises(ValueError, match="orders"):
        rebuild(ds, proj, db, tmp_path / "rebuilt.sqlite")


def test_refuses_existing_out(shop, tmp_path):
    proj, db, ds, out = _built(shop, tmp_path)
    with pytest.raises(FileExistsError):
        rebuild(ds, proj, db, out)
    args = ["rebuild", str(ds), "--project", str(proj), "--db", str(db), "--out", str(out)]
    assert cli.main(args) == 2
    assert cli.main([*args, "--force"]) == 0


def test_views_run_in_utc_whatever_the_host(shop, tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "Australia/Sydney")
    proj, db = shop
    ds = ingest(proj, db, tmp_path / "ds")
    views = (proj / "specs" / "views.sql").read_text()
    (proj / "specs" / "views.sql").write_text(
        views.replace("SELECT ext_id AS cid, city FROM customers;",
                      "SELECT ext_id AS cid, current_setting('TimeZone') AS city FROM customers;"))
    out = rebuild(ds, proj, db, tmp_path / "rebuilt.sqlite")
    assert {r[0] for r in _rows(out, "SELECT city FROM customers")} == {"UTC"}
