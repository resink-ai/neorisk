COUNTS = {
    "companies_created": 14003,
    "companies_snapshot": 14003,
    "job_posted": 78769,
    "job_skills_created": 366960,
    "skills_created": 26,
}


def test_jobpostings_dataset(built):
    manifest, report, types = built("jobpostings")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 4
    assert len(report["queries"]) == 1
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
