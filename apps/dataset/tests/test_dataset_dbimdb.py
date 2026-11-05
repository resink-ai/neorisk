COUNTS = {
    "cast_credited": 82837,
    "countries_created": 34,
    "genres_created": 328,
    "languages_created": 32,
    "locations_created": 559,
    "movie_released": 3475,
    "movies_snapshot": 3475,
    "persons_created": 37565,
    "persons_snapshot": 37565,
    "producer_credited": 11751
}


def test_dbimdb_dataset(built):
    manifest, report, types = built("dbimdb")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 13
    assert len(report["queries"]) == 5
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
