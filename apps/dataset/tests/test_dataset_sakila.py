COUNTS = {
    "actor_created": 200,
    "address_created": 603,
    "category_created": 16,
    "city_created": 600,
    "country_created": 109,
    "customer_created": 599,
    "film_actor_created": 5462,
    "film_created": 1000,
    "inventory_created": 4581,
    "language_created": 6,
    "actor_snapshot": 200,
    "address_snapshot": 603,
    "category_snapshot": 16,
    "city_snapshot": 600,
    "country_snapshot": 109,
    "customer_snapshot": 599,
    "film_actor_snapshot": 5462,
    "film_snapshot": 1000,
    "inventory_snapshot": 4581,
    "language_snapshot": 6,
    "staff_snapshot": 2,
    "store_snapshot": 2,
    "payment_taken": 16049,
    "rental_returned": 15861,
    "rental_started": 16044,
    "staff_created": 2,
    "store_created": 2
}


def test_sakila_dataset(built):
    manifest, report, types = built("sakila")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 16
    assert len(report["queries"]) == 9
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
