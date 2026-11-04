COUNTS = {
    "source_row_duplicated": 6842,
    "species_created": 132,
    "trees_created": 683788,
    "trees_snapshot": 683788,
    "zip_incomes_created": 216
}


def test_nyctrees_dataset(built):
    manifest, report, types = built("nyctrees")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 2
    assert len(report["queries"]) == 2
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
