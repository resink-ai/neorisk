from conftest import roundtrip

from neorisk_simkit.io import read


def test_pizzarunner_round_trip(tmp_path, capsys):
    summary, ds = roundtrip("pizzarunner", tmp_path, capsys)
    assert summary["failed"] == []
    assert summary["tables"] == 10
    assert summary["queries"] == 3
    run = read(ds)
    assert {k: v.height for k, v in run.events.items()} == {
        "pizza_ordered": 14, "order_picked_up": 8, "order_delivered": 8, "order_cancelled": 2}
    assert {k: v.height for k, v in run.entities.items()} == {
        "runners": 4, "pizzas": 2, "toppings": 12, "customers": 5}
