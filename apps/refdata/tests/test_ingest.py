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
