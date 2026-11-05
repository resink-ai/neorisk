COUNTS = {
    "accounts_created": 351,
    "accounts_snapshot": 351,
    "order_placed": 6912,
    "region_created": 4,
    "sales_reps_created": 50,
    "sales_reps_snapshot": 50,
    "web_visited": 9073
}


def test_parchposey_dataset(built):
    manifest, report, types = built("parchposey")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 5
    assert len(report["queries"]) == 1
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
