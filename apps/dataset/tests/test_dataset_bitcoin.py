COUNTS = {
    "trade": 22918,
    "price_published": 3404,
    "members_created": 14,
    "members_snapshot": 14,
    "tickers_created": 2
}


def test_bitcoin_dataset(built):
    manifest, report, types = built("bitcoin")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 3
    assert len(report["queries"]) == 2
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
