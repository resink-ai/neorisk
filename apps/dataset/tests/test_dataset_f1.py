COUNTS = {
    "circuits_created": 77,
    "circuits_snapshot": 77,
    "constructor_race_points_reported": 12505,
    "constructor_standings_published": 13271,
    "constructors_created": 212,
    "constructors_snapshot": 212,
    "drive_override_recorded": 39,
    "driver_standings_published": 34595,
    "drivers_created": 859,
    "drivers_snapshot": 859,
    "lap_completed": 575029,
    "liveries_created": 64,
    "liveries_snapshot": 64,
    "pit_stop_made": 10990,
    "qualifying_classified": 10254,
    "race_result_classified": 26519,
    "race_scheduled": 1125,
    "seasons_created": 75,
    "seasons_snapshot": 75,
    "short_constructor_names_created": 44,
    "short_grand_prix_names_created": 40,
    "sprint_classified": 300,
    "status_created": 139,
    "tdr_overrides_created": 48
}


def test_f1_dataset(built):
    manifest, report, types = built("f1")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 29
    assert len(report["queries"]) == 9
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
