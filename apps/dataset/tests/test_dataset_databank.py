COUNTS = {
    "account_opened": 500,
    "customers_created": 500,
    "node_reassigned": 3000,
    "regions_created": 5,
    "transaction_posted": 5868
}


def test_databank_dataset(built):
    manifest, report, types = built("databank")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 3
    assert len(report["queries"]) == 6
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
