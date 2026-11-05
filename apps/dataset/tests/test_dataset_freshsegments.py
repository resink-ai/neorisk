COUNTS = {
    "interest_metrics_reported": 14273,
    "interest_modified": 709,
    "interests_created": 1209
}


def test_freshsegments_dataset(built):
    manifest, report, types = built("freshsegments")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 2
    assert len(report["queries"]) == 2
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
