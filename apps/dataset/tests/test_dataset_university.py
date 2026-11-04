COUNTS = {
    "course_created": 7,
    "faculty_created": 8,
    "faculty_snapshot": 8,
    "grade_recorded": 37,
    "offering_created": 13,
    "student_created": 11,
    "student_enrolled": 37,
    "student_snapshot": 11
}


def test_university_dataset(built):
    manifest, report, types = built("university")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 5
    assert len(report["queries"]) == 1
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
