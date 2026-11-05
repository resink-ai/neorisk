COUNTS = {
    "case_indexed": 94243,
    "collision_occurred": 94243,
    "collision_processed": 94243,
    "party_recorded": 186692,
    "victim_recorded": 96393
}


def test_switrs_dataset(built):
    manifest, report, types = built("switrs")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 4
    assert len(report["queries"]) == 3
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
