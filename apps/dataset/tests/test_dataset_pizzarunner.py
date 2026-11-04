COUNTS = {
    "pizza_ordered": 14,
    "order_picked_up": 8,
    "order_delivered": 8,
    "order_cancelled": 2,
    "runners_created": 4,
    "pizzas_created": 2,
    "toppings_created": 12,
    "customers_created": 5
}


def test_pizzarunner_dataset(built):
    manifest, report, types = built("pizzarunner")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 10
    assert len(report["queries"]) == 3
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
