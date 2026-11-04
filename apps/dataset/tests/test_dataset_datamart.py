COUNTS = {
    "weekly_sales_reported": 17117
}


def test_datamart_dataset(built):
    manifest, report, types = built("datamart")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 2
    assert len(report["queries"]) == 2
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
