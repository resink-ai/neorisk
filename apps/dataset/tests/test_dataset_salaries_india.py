COUNTS = {
    "salary_aggregate_reported": 4344,
    "salary_listing_created": 4344
}


def test_salaries_india_dataset(built):
    manifest, report, types = built("salaries_india")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 1
    assert len(report["queries"]) == 1
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
