from datetime import UTC, datetime

import pytest
from conftest import ROWS, make_db

from neorisk_simkit.checks import failed, run_checks
from neorisk_simkit.io import read
from refdata import cli
from refdata.ingest import IngestError, ingest


def test_ingest_layout(shop, tmp_path):
    proj, db = shop
    out = ingest(proj, db, tmp_path / "ds")
    run = read(out)
    assert run.events["order_placed"].height == 3
    assert run.events["order_paid"].height == 2
    assert run.entities["customers"].height == 2
    assert run.manifest["provenance"]["source"] == "ingest"
    assert run.manifest["provenance"]["file"] == "shop.sqlite"


def test_values_cast(shop, tmp_path):
    proj, db = shop
    ev = read(ingest(proj, db, tmp_path / "ds")).events["order_placed"].sort("order_ext")
    assert ev["total"].to_list() == [1050, 300, 9999]
    assert ev["note"].to_list() == ["hi", None, ""]
    assert ev["event_time"][0] == datetime(2021, 1, 2, 9, 5, tzinfo=UTC)
    assert ev["customer_id"].to_list() == [1, 2, 1]


def test_common_columns(shop, tmp_path):
    proj, db = shop
    run = read(ingest(proj, db, tmp_path / "ds"))
    ev = run.all_events(["seq", "event_id", "event_time", "partition_id", "event_type"])
    assert ev["seq"].to_list() == [1, 2, 3, 4, 5]
    assert ev["event_id"].to_list() == ev["seq"].to_list()
    assert ev["event_time"].is_sorted()
    assert ev["partition_id"].n_unique() == 2


def test_structural_checks_pass(shop, tmp_path):
    proj, db = shop
    assert failed(run_checks(read(ingest(proj, db, tmp_path / "ds")))) == []


def test_unmatched_ref_named(tmp_path, shop):
    proj, _ = shop
    db = make_db(tmp_path / "bad.sqlite", ROWS + [("o4", "zz", "1/4/2021 1:00:00 AM", None,
                                                   1.0, None)])
    with pytest.raises(IngestError) as e:
        ingest(proj, db, tmp_path / "ds")
    assert all(s in str(e.value) for s in ("order_placed", "customer_id", "zz"))


def test_refuses_existing_out(shop, tmp_path, capsys):
    proj, db = shop
    ingest(proj, db, tmp_path / "ds")
    with pytest.raises(FileExistsError):
        ingest(proj, db, tmp_path / "ds")
    assert cli.main(["ingest", str(proj), "--db", str(db), "--out", str(tmp_path / "ds")]) == 2
    assert cli.main(["ingest", str(proj), "--db", str(db), "--out", str(tmp_path / "ds"),
                     "--force"]) == 0


def test_missing_db_exit_2(shop, tmp_path, capsys):
    proj, _ = shop
    assert cli.main(["ingest", str(proj), "--db", str(tmp_path / "nope.sqlite")]) == 2
    assert "run: uv run refdata fetch" in capsys.readouterr().err


def test_block_without_order_by(shop, tmp_path):
    proj, db = shop
    sql = (proj / "specs" / "ingest.sql").read_text()
    (proj / "specs" / "ingest.sql").write_text(sql.replace(" ORDER BY cid", ""))
    with pytest.raises(IngestError, match="ORDER BY"):
        ingest(proj, db, tmp_path / "ds")


def test_missing_block_named(shop, tmp_path):
    proj, db = shop
    sql = (proj / "specs" / "ingest.sql").read_text()
    (proj / "specs" / "ingest.sql").write_text(sql.split("-- event: order_paid")[0])
    with pytest.raises(IngestError, match="order_paid"):
        ingest(proj, db, tmp_path / "ds")


def test_entity_ref_mapped(shop, tmp_path):
    proj, db = shop
    pack = (proj / "specs" / "pack.py").read_text()
    (proj / "specs" / "pack.py").write_text(pack + (
        '    p.entity("cards", key="card_id",\n'
        '             cols={"ext_id": text(), "customer_id": ref("customers")})\n'))
    sql = (proj / "specs" / "ingest.sql").read_text()
    (proj / "specs" / "ingest.sql").write_text(
        sql + "-- entity: cards\nSELECT 'k' || cid AS ext_id, cid AS customer_id "
              "FROM customers ORDER BY cid;\n")
    cards = read(ingest(proj, db, tmp_path / "ds")).entities["cards"]
    assert cards["customer_id"].to_list() == [1, 2]


def test_manifest_anchors_the_pack(shop, tmp_path):
    from neorisk_simkit.project import load_project
    proj, db = shop
    run = read(ingest(proj, db, tmp_path / "ds"))
    assert run.manifest["provenance"]["pack_revision"] == load_project(proj).revision()


def test_force_never_deletes_a_non_dataset(shop, tmp_path):
    proj, db = shop
    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "notes.txt").write_text("keep me")
    with pytest.raises(FileExistsError, match="not a refdata dataset"):
        ingest(proj, db, precious, force=True)
    assert (precious / "notes.txt").read_text() == "keep me"


def test_run_window_covers_late_entity(shop, tmp_path):
    """An entity created after the last event (Pizza Runner's runner 4) stays inside the run."""
    proj, db = shop
    sql = (proj / "specs" / "ingest.sql").read_text()
    (proj / "specs" / "ingest.sql").write_text(sql.replace(
        "SELECT cid AS ext_id, city FROM customers ORDER BY cid;",
        "SELECT cid AS ext_id, city, '2021-02-01 00:00:00' AS created_at FROM customers "
        "ORDER BY cid;"))
    run = read(ingest(proj, db, tmp_path / "ds"))
    start = datetime.fromisoformat(run.manifest["run"]["start"])
    end = start.timestamp() + run.manifest["run"]["days"] * 86400
    assert end >= datetime(2021, 2, 1, tzinfo=UTC).timestamp()
    assert failed(run_checks(run)) == []


def test_empty_block_writes_typed_empty_table(shop, tmp_path):
    """A block with no rows (Sakila film_text, weblog's noise log) is an empty, typed table."""
    from refdata.rebuild import rebuild
    proj, db = shop
    sql = (proj / "specs" / "ingest.sql").read_text()
    (proj / "specs" / "ingest.sql").write_text(sql.replace("WHERE paid IS NOT NULL",
                                                           "WHERE paid IS NOT NULL AND 0"))
    run = read(ingest(proj, db, tmp_path / "ds"))
    paid = run.events["order_paid"]
    assert paid.height == 0
    assert dict(paid.schema)["customer_id"] == run.events["order_placed"].schema["customer_id"]
    assert failed(run_checks(run)) == []
    from neorisk_simkit.io.log import write_log
    write_log(run, tmp_path / "log")
    out = rebuild(tmp_path / "log", proj, db, tmp_path / "rebuilt.sqlite")
    import sqlite3
    con = sqlite3.connect(out)
    assert con.execute("SELECT count(*) FROM orders WHERE paid IS NULL").fetchone() == (3,)
    con.close()


def test_created_names_from_entity_block(shop):
    from refdata.ingest import created_names
    proj, _ = shop
    sql = (proj / "specs" / "ingest.sql").read_text()
    (proj / "specs" / "ingest.sql").write_text(
        sql.replace("-- entity: customers", "-- entity: customers event=customer_signed_up"))
    assert created_names(proj) == {"customers": "customer_signed_up"}


def test_bad_created_name_refused(shop):
    from refdata.ingest import created_names
    proj, _ = shop
    sql = (proj / "specs" / "ingest.sql").read_text()
    (proj / "specs" / "ingest.sql").write_text(
        sql.replace("-- entity: customers", "-- entity: customers event=Customer-Signup"))
    with pytest.raises(IngestError, match="Customer-Signup"):
        created_names(proj)
