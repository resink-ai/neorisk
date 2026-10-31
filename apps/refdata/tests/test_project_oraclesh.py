from conftest import roundtrip

from neorisk_simkit.io import read


def test_oraclesh_round_trip(tmp_path, capsys):
    summary, ds = roundtrip("oraclesh", tmp_path, capsys)
    assert summary["failed"] == []
    assert summary["tables"] == 10
    assert summary["queries"] == 6
    run = read(ds)
    assert {k: v.height for k, v in run.events.items()} == {
        "price_quoted": 82112, "unit_sold": 918843}
    products = run.entities["products"]
    assert products.height == 75
    assert products["catalogued"].sum() == 24
