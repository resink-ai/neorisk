COUNTS = {
    "feature_profiled": 1547,
    "feature_weighted": 2887,
    "model_scored": 2872,
    "model_weighted": 2567,
    "problems_created": 20,
    "run_configured": 101,
    "step_completed": 303
}


def test_stacking_dataset(built):
    manifest, report, types = built("stacking")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 7
    assert len(report["queries"]) == 3
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
