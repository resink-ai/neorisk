"""school: the School Scheduling database of *SQL Queries for Mere Mortals* (Viescas and
Hernandez). Students enrol in class sections, then complete them with a grade or withdraw.
Stage 1, schema only: the events are ingested from the Spider2 tables
(docs/research/spider2/school.md); stage 2 adds the behavior.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, f64, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("buildings", key="building_id", doc="Lookups are created at T0 = 2017-09-11",
             cols={"ext_id": text(doc="the BuildingCode"), "building_name": opt(text()),
                   "number_of_floors": opt(i64())})
    p.entity("class_rooms", key="class_room_id",
             cols={"ext_id": text(), "building_id": opt(ref("buildings"))})
    p.entity("staff", key="staff_id",
             doc="Hired at DateHired; address, phone, position and salary are a snapshot",
             cols={"ext_id": text(), "first_name": opt(text()), "last_name": opt(text())})
    p.entity("departments", key="department_id",
             cols={"ext_id": text(), "dept_name": opt(text())})
    p.entity("categories", key="category_id",
             cols={"ext_id": text(doc="the CategoryID, e.g. 'ENG'"), "description": opt(text()),
                   "department_id": opt(ref("departments"))})
    p.entity("subjects", key="subject_id",
             cols={"ext_id": text(), "category_id": opt(ref("categories")),
                   "subject_code": opt(text()), "subject_name": opt(text()),
                   "subject_prereq": opt(text(doc="a SubjectCode, not a SubjectID")),
                   "subject_description": opt(text())})
    p.entity("majors", key="major_id", cols={"ext_id": text(), "major": opt(text())})
    p.entity("student_class_status", key="class_status_id",
             cols={"ext_id": text(), "description": opt(text())})
    p.entity("faculty", key="faculty_id",
             doc="1:1 with staff, hired at their DateHired; title, status, tenured are a snapshot",
             cols={"ext_id": text(doc="the StaffID"), "staff_id": ref("staff")})
    p.entity("faculty_categories", key="fc_id",
             cols={"ext_id": text(doc="'<StaffID>/<CategoryID>'"), "faculty_id": ref("faculty"),
                   "category_id": ref("categories")})
    p.entity("faculty_subjects", key="fs_id",
             cols={"ext_id": text(doc="'<StaffID>/<SubjectID>'"), "faculty_id": ref("faculty"),
                   "subject_id": ref("subjects")})
    p.entity("classes", key="class_id", doc="A section, created at its first meeting",
             cols={"ext_id": text(), "subject_id": opt(ref("subjects")),
                   "class_room_id": opt(ref("class_rooms")), "credits": opt(i64()),
                   "duration": opt(i64(doc="minutes")), "monday": i64(), "tuesday": i64(),
                   "wednesday": i64(), "thursday": i64(), "friday": i64(), "saturday": i64()})
    p.entity("faculty_classes", key="fcl_id", doc="The class's teacher, created with the class",
             cols={"ext_id": text(doc="'<ClassID>/<StaffID>'"), "class_id": ref("classes"),
                   "staff_id": ref("staff")})
    p.entity("students", key="student_id",
             doc="Created at T0; address, phone, major and StudGPA are a snapshot",
             cols={"ext_id": text(), "first_name": opt(text()), "last_name": opt(text())})
    p.event("student_enrolled", doc="At the class's start (a rule: no enrolment date)",
            cols={"student_id": ref("students"), "class_id": ref("classes")})
    p.event("class_completed", doc="At T_end = 2018-01-14 (a rule), with the grade",
            cols={"student_id": ref("students"), "class_id": ref("classes"), "grade": f64()})
    p.event("class_withdrawn", doc="At T_end = 2018-01-14 (a rule)",
            cols={"student_id": ref("students"), "class_id": ref("classes")})
    p.event("buildings_snapshot", doc="State at N: the amenity flags",
            cols={"building_id": ref("buildings"), "elevator_access": i64(),
                  "site_parking_available": i64()})
    p.event("class_rooms_snapshot", doc="State at N", cols={"class_room_id": ref("class_rooms"),
                                                             "phone_available": i64()})
    p.event("departments_snapshot", doc="State at N: the current chair",
            cols={"department_id": ref("departments"), "dept_chair": opt(ref("staff"))})
    p.event("faculty_subjects_snapshot", doc="State at N: the current rating",
            cols={"fs_id": ref("faculty_subjects"), "proficiency_rating": opt(f64())})
    p.event("students_snapshot",
            doc="State at N: address, phone, major and the stored GPA (not a function of the grades)",
            cols={"student_id": ref("students"), "street_address": opt(text()),
                  "city": opt(text()), "state": opt(text()), "zip": opt(text()),
                  "area_code": opt(text()), "phone": opt(text()),
                  "major_id": opt(ref("majors")), "stud_gpa": opt(f64())})
    p.event("staff_snapshot", doc="State at N: address, phone, position and salary",
            cols={"staff_id": ref("staff"), "street_address": opt(text()), "city": opt(text()),
                  "state": opt(text()), "zip": opt(text()), "area_code": opt(text()),
                  "phone": opt(text()), "position": opt(text()), "salary": opt(f64())})
    p.event("faculty_snapshot", doc="State at N",
            cols={"faculty_id": ref("faculty"), "title": opt(text()), "status": opt(text()),
                  "tenured": i64()})
