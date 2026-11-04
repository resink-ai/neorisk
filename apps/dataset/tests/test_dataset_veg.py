COUNTS = {
    "categories_created": 6,
    "item_returned": 461,
    "item_sold": 878042,
    "items_created": 251,
    "wholesale_price_quoted": 55982
}


def test_veg_dataset(built):
    manifest, report, types = built("veg")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 4
    assert len(report["queries"]) == 2
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
