COUNTS = {
    "buildings_created": 6,
    "categories_created": 19,
    "class_completed": 68,
    "class_rooms_created": 47,
    "class_withdrawn": 2,
    "classes_created": 147,
    "departments_created": 5,
    "faculty_categories_created": 76,
    "faculty_classes_created": 145,
    "faculty_created": 24,
    "faculty_snapshot": 24,
    "faculty_subjects_created": 110,
    "majors_created": 7,
    "staff_created": 27,
    "staff_snapshot": 27,
    "student_class_status_created": 3,
    "student_enrolled": 120,
    "students_created": 19,
    "students_snapshot": 19,
    "subjects_created": 56
}


def test_school_dataset(built):
    manifest, report, types = built("school")
    assert [r.name for r in report["tables"] + report["queries"] if not r.ok] == []
    assert len(report["tables"]) == 15
    assert len(report["queries"]) == 1
    assert types == {k: v for k, v in COUNTS.items() if v}
    assert manifest["counts"]["log"] == sum(COUNTS.values())
