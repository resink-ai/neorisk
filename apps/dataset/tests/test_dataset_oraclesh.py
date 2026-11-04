COUNTS = {
    "channels_created": 5,
    "countries_created": 35,
    "customers_created": 55500,
    "demographics_created": 4500,
    "price_quoted": 82112,
    "products_created": 75,
    "promotions_created": 503,
    "times_created": 1826,
    "unit_sold": 918843
}


def test_oraclesh_dataset(built):
    manifest, report, types = built("oraclesh")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 10
    assert len(report["queries"]) == 6
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
