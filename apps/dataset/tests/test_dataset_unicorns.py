COUNTS = {
    "companies_created": 1074,
    "companies_snapshot": 1074,
    "source_row_duplicated": 33
}


def test_unicorns_dataset(built):
    manifest, report, types = built("unicorns")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 3
    assert len(report["queries"]) == 2
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
