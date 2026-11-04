COUNTS = {
    "legislators_created": 12518,
    "term_started": 44063,
    "term_ended": 43526,
}


def test_legislators_dataset(built):
    manifest, report, types = built("legislators")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 3
    assert len(report["queries"]) == 4
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
