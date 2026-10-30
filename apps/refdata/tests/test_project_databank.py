from conftest import roundtrip

from neorisk_simkit.io import read


def test_databank_round_trip(tmp_path, capsys):
    summary, ds = roundtrip("databank", tmp_path, capsys)
    assert summary["failed"] == []
    assert summary["queries"] == 6
    ev = read(ds).events
    assert ev["account_opened"].height == 500
    assert ev["node_reassigned"].height == 3000
    tx = ev["transaction_posted"]
    assert tx.height == 5868
    assert dict(tx["txn_type"].cast(str).value_counts().iter_rows()) == {
        "deposit": 2671, "purchase": 1617, "withdrawal": 1580}
