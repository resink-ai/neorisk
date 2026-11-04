COUNTS = {
    "agents_created": 9,
    "customers_created": 15,
    "engagement_booked": 111,
    "entertainer_members_created": 40,
    "entertainer_styles_created": 32,
    "entertainers_created": 13,
    "members_created": 25,
    "musical_preferences_created": 36,
    "musical_styles_created": 25
}


def test_entertainment_dataset(built):
    manifest, report, types = built("entertainment")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 13
    assert len(report["queries"]) == 3
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
