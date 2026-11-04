COUNTS = {
    "staff_clocked": 236,
    "staff_created": 26
}


def test_staffhours_dataset(built):
    manifest, report, types = built("staffhours")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 1
    assert len(report["queries"]) == 0
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
