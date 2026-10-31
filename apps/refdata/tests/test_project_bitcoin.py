from conftest import roundtrip

from neorisk_simkit.io import read


def test_bitcoin_round_trip(tmp_path, capsys):
    summary, ds = roundtrip("bitcoin", tmp_path, capsys)
    assert summary["failed"] == []
    assert summary["tables"] == 3
    assert summary["queries"] == 2
    run = read(ds)
    assert {k: v.height for k, v in run.events.items()} == {"trade": 22918, "price_published": 3404}
    assert {k: v.height for k, v in run.entities.items()} == {"members": 14, "tickers": 2}
    trades = run.events["trade"].sort("seq")
    assert trades["txn_id"].to_list() == list(range(1, 22919))      # seq keeps txn_id order
