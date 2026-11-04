COUNTS = {
    "aliens_created": 50000,
    "aliens_snapshot": 50000
}


def test_aliens_dataset(built):
    manifest, report, types = built("aliens")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 4
    assert len(report["queries"]) == 1
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
