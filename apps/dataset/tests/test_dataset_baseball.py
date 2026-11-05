COUNTS = {
    "all_star_selected": 5069,
    "appearances_reported": 100951,
    "batting_line_reported": 101332,
    "batting_postseason_reported": 11690,
    "college_attended": 17350,
    "college_created": 1211,
    "fielding_line_reported": 170526,
    "fielding_postseason_reported": 12311,
    "hof_ballot_recorded": 4120,
    "home_games_reported": 2944,
    "manager_award_vote_received": 414,
    "manager_award_won": 177,
    "manager_half_reported": 93,
    "manager_stint_reported": 3405,
    "outfield_split_reported": 12028,
    "park_created": 250,
    "pitching_line_reported": 44139,
    "pitching_postseason_reported": 5109,
    "player_award_vote_received": 6795,
    "player_award_won": 6078,
    "player_created": 18858,
    "player_snapshot_taken": 18846,
    "postseason_series_decided": 307,
    "salary_reported": 25575,
    "season_created": 145,
    "team_franchise_created": 120,
    "team_half_reported": 52,
    "team_season_reported": 2805
}


def test_baseball_dataset(built):
    manifest, report, types = built("baseball")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 26
    assert len(report["queries"]) == 2
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
