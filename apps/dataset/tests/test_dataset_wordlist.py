COUNTS = {
    "words_created": 370103,
    "source_row_duplicated": 3701
}


def test_wordlist_dataset(built):
    manifest, report, types = built("wordlist")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 1
    assert len(report["queries"]) == 2
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
