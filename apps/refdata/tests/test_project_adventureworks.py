from conftest import roundtrip

from neorisk_simkit.io import read


def test_adventureworks_round_trip(tmp_path, capsys):
    summary, ds = roundtrip("adventureworks", tmp_path, capsys)
    assert summary["failed"] == []
    assert summary["tables"] == 13
    assert summary["queries"] == 1
    run = read(ds)
    assert {k: v.height for k, v in run.events.items()} == {
        "order_placed": 31465, "order_line_added": 121317, "order_shipped": 31465,
        "currency_rate_published": 13532, "quota_set": 163, "product_reviewed": 4}
    assert sum(v.height for v in run.entities.values()) == 1443
