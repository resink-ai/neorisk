from conftest import roundtrip

from neorisk_simkit.io import read


def test_chinook_round_trip(tmp_path, capsys):
    summary, ds = roundtrip("chinook", tmp_path, capsys)
    assert summary["failed"] == []
    assert summary["tables"] == 11
    assert summary["queries"] == 3
    run = read(ds)
    assert {k: v.height for k, v in run.events.items()} == {
        "invoice_issued": 412, "invoice_line_added": 2240}
    assert sum(v.height for v in run.entities.values()) == 12955
