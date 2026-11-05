COUNTS = {
    "country_currencies_created": 109,
    "country_currencies_snapshot": 109,
    "currency_rate_published": 13532,
    "order_line_added": 121317,
    "order_placed": 31465,
    "order_shipped": 31465,
    "product_categories_created": 4,
    "product_categories_snapshot": 4,
    "product_descriptions_created": 762,
    "product_descriptions_snapshot": 762,
    "product_reviewed": 4,
    "product_subcategories_created": 37,
    "product_subcategories_snapshot": 37,
    "products_created": 504,
    "products_snapshot": 504,
    "quota_set": 163,
    "salespersons_created": 17,
    "salespersons_snapshot": 17,
    "territories_created": 10,
    "territories_snapshot": 10
}


def test_adventureworks_dataset(built):
    manifest, report, types = built("adventureworks")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 13
    assert len(report["queries"]) == 1
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
