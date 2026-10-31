from conftest import roundtrip

from neorisk_simkit.io import read


def test_sakila_round_trip(tmp_path, capsys):
    summary, ds = roundtrip("sakila", tmp_path, capsys)
    assert summary["failed"] == []
    assert summary["tables"] == 16
    assert summary["queries"] == 9
    run = read(ds)
    assert {k: v.height for k, v in run.events.items()} == {
        "rental_started": 16044, "payment_taken": 16049, "rental_returned": 15861}
    assert sum(v.height for v in run.entities.values()) == 13180
    assert run.events["payment_taken"]["rental_id"].null_count() == 5
