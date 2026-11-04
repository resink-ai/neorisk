COUNTS = {
    "cities_created": 44622,
    "countries_created": 241,
    "countries_snapshot": 241,
    "currencies_created": 254,
    "languages_created": 608
}


def test_cities_dataset(built):
    manifest, report, types = built("cities")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 4
    assert len(report["queries"]) == 4
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
