COUNTS = {
    "bowlers_created": 34,
    "bowlers_snapshot": 34,
    "game_bowled": 1344,
    "match_scheduled": 57,
    "teams_created": 10,
    "teams_snapshot": 10,
    "tournaments_created": 20,
    "wazips_created": 523
}


def test_bowling_dataset(built):
    manifest, report, types = built("bowling")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 11
    assert len(report["queries"]) == 1
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
