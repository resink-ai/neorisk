COUNTS = {
    "daily_totals_reported": 1000,
    "source_row_duplicated": 10
}


def test_covidstates_dataset(built):
    manifest, report, types = built("covidstates")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 1
    assert len(report["queries"]) == 0
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
