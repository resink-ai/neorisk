COUNTS = {
    "customer_deduction_set": 418,
    "customers_created": 209,
    "monthly_sales_reported": 971631,
    "product_priced": 579,
    "products_created": 397
}


def test_atliq_dataset(built):
    manifest, report, types = built("atliq")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 6
    assert len(report["queries"]) == 2
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
