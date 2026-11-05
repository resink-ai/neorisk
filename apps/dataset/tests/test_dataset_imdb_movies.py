COUNTS = {
    "cast_credited": 15615,
    "director_credited": 3867,
    "erd_created": 25,
    "movie_genre_tagged": 14662,
    "movie_rated": 7997,
    "movie_released": 7997,
    "movies_snapshot": 4273,
    "names_created": 25735,
    "names_snapshot": 15852
}


def test_imdb_movies_dataset(built):
    manifest, report, types = built("imdb_movies")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 7
    assert len(report["queries"]) == 2
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
