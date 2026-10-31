from conftest import roundtrip

from neorisk_simkit.io import read


def test_northwind_round_trip(tmp_path, capsys):
    summary, ds = roundtrip("northwind", tmp_path, capsys)
    assert summary["failed"] == []
    assert summary["tables"] == 15
    assert summary["queries"] == 2
    run = read(ds)
    assert {k: v.height for k, v in run.events.items()} == {
        "order_placed": 830, "order_line_added": 2155, "order_shipped": 809}
    assert sum(v.height for v in run.entities.values()) == 381
