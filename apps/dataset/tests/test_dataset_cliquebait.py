COUNTS = {
    "campaigns_created": 3,
    "cookie_issued": 1782,
    "event_kinds_created": 5,
    "page_event": 32734,
    "pages_created": 13
}


def test_cliquebait_dataset(built):
    manifest, report, types = built("cliquebait")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 5
    assert len(report["queries"]) == 1
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
