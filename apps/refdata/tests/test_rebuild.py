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


def _log(proj, db, tmp_path):
    """Ingest the shop, write its event log, and return the log's root."""
    from neorisk_simkit.io import read
    from neorisk_simkit.io.log import write_log
    from refdata.ingest import owners
    write_log(read(ingest(proj, db, tmp_path / "ds")), tmp_path / "log", owners=owners(proj))
    return tmp_path / "log"


def _built(shop, tmp_path):
    proj, db = shop
    log = _log(proj, db, tmp_path)
    return proj, db, log, rebuild(log, proj, db, tmp_path / "rebuilt.sqlite")


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
    ds = _log(proj, db, tmp_path)
    views = (proj / "specs" / "build.sql").read_text()
    (proj / "specs" / "build.sql").write_text(views.replace(", p.note", ""))
    with pytest.raises(ValueError, match="note"):
        rebuild(ds, proj, db, tmp_path / "rebuilt.sqlite")


def test_missing_table_block_named(shop, tmp_path):
    proj, db = shop
    ds = _log(proj, db, tmp_path)
    views = (proj / "specs" / "build.sql").read_text()
    (proj / "specs" / "build.sql").write_text(views.split("-- table: orders")[0])
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
    ds = _log(proj, db, tmp_path)
    views = (proj / "specs" / "build.sql").read_text()
    (proj / "specs" / "build.sql").write_text(
        views.replace("SELECT ext_id AS cid, city FROM customers;",
                      "SELECT ext_id AS cid, current_setting('TimeZone') AS city FROM customers;"))
    out = rebuild(ds, proj, db, tmp_path / "rebuilt.sqlite")
    assert {r[0] for r in _rows(out, "SELECT city FROM customers")} == {"UTC"}


def test_rebuild_reads_only_the_log(shop, tmp_path):
    import shutil

    from neorisk_simkit.io import read
    from neorisk_simkit.io.log import write_log
    from refdata.ingest import owners
    proj, db = shop
    ds = ingest(proj, db, tmp_path / "ds")
    write_log(read(ds), tmp_path / "log", owners=owners(proj))
    shutil.rmtree(ds / "events")
    shutil.rmtree(ds / "entities")
    out = rebuild(tmp_path / "log", proj, db, tmp_path / "rebuilt.sqlite")
    q = "SELECT oid, cid, placed, paid, total, note FROM orders ORDER BY oid"
    assert _rows(out, q) == _rows(db, q)
