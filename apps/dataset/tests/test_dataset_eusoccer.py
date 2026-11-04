COUNTS = {
    "countries_created": 11,
    "leagues_created": 11,
    "match_played": 25979,
    "player_rated": 183978,
    "players_created": 11060,
    "players_snapshot": 11060,
    "team_rated": 1458,
    "teams_created": 299
}


def test_eusoccer_dataset(built):
    manifest, report, types = built("eusoccer")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 7
    assert len(report["queries"]) == 5
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
