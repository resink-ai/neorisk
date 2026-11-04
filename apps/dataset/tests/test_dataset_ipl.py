COUNTS = {
    "ball_bowled": 134704,
    "innings_started": 1136,
    "match_completed": 567,
    "match_scheduled": 567,
    "player_named": 12495,
    "players_created": 469,
    "teams_created": 13,
    "toss_decided": 567
}


def test_ipl_dataset(built):
    manifest, report, types = built("ipl")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 8
    assert len(report["queries"]) == 11
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
