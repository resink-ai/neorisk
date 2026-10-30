from conftest import roundtrip

from neorisk_simkit.io import read


def test_cliquebait_round_trip(tmp_path, capsys):
    summary, ds = roundtrip("cliquebait", tmp_path, capsys)
    assert summary["failed"] == []
    assert summary["queries"] == 1
    run = read(ds)
    assert run.events["page_event"].height == 32734
    assert run.entities["cookies"].height == 1782
    assert run.entities["pages"].height == 13
