COUNTS = {
    "agent_hired": 9,
    "agents_snapshot": 9,
    "customers_created": 15,
    "customers_snapshot": 15,
    "engagement_booked": 111,
    "entertainer_members_created": 40,
    "entertainer_members_snapshot": 40,
    "entertainer_styles_created": 32,
    "entertainer_styles_snapshot": 32,
    "entertainer_registered": 13,
    "entertainers_snapshot": 13,
    "members_created": 25,
    "members_snapshot": 25,
    "musical_preferences_created": 36,
    "musical_preferences_snapshot": 36,
    "musical_styles_created": 25
}


def test_entertainment_dataset(built):
    manifest, report, types = built("entertainment")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 13
    assert len(report["queries"]) == 3
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
