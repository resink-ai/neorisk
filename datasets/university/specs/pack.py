"""University: Mannino's textbook sample. Students enrol in course offerings and get a grade;
faculty teach the offerings and report to a supervisor. Stage 1, schema only: the events are
ingested from the Spider2 tables (docs/research/spider2/university.md).

Only faculty hire dates are real times. Enrollment happens at its offering's term start and the
grade at its term end, by a term-calendar rule. Addresses, department, supervisor, major,
rank, salary, class, GPA and the offering's teacher are snapshot columns at N = 2010-08-31.
Grades and GPAs travel as integers of tenths.
"""

from dataclasses import dataclass

from neorisk_simkit.spec import Pack, cat, i64, opt, ref, text

SCHEMA_VERSION = 1


@dataclass
class Config:
    pass


def define(p: Pack) -> None:
    p.entity("course", key="course_id", doc="Created at the catalog start by rule, 2009-07-01",
             cols={"ext_id": text(doc="CourseNo"), "crs_desc": text(), "crs_units": i64()})
    p.entity("faculty", key="faculty_id",
             doc="Hired at FacHireDate; address, dept, supervisor, rank and salary are a snapshot",
             cols={"ext_id": text(doc="FacNo"), "first_name": text(), "last_name": text()})
    p.entity("student", key="student_id",
             doc="Created at the catalog start by rule; address, major, class and GPA are a snapshot",
             cols={"ext_id": text(doc="StdNo"), "first_name": text(), "last_name": text()})
    p.entity("offering", key="offering_id",
             doc="Created at its term start by rule; the assigned teacher is a snapshot",
             cols={"ext_id": text(doc="OfferNo"), "course_id": ref("course"),
                   "term": cat("FALL", "WINTER", "SPRING", "SUMMER"), "year": i64(),
                   "location": text(), "time": text(doc="'10:30 AM', verbatim"),
                   "days": text()})
    p.event("student_enrolled", doc="At the offering's term start (a rule)",
            cols={"student_id": ref("student"), "offering_id": ref("offering")})
    p.event("grade_recorded", doc="At the offering's term end (a rule)",
            cols={"student_id": ref("student"), "offering_id": ref("offering"),
                  "grade_tenths": i64(doc="EnrGrade × 10")})
    p.event("faculty_snapshot", doc="State at N: address, dept, supervisor, rank and salary",
            cols={"faculty_id": ref("faculty"), "city": text(), "state": text(), "zip": text(),
                  "dept": cat("MS", "FIN", "CS"), "supervisor_id": opt(ref("faculty")),
                  "rank": cat("ASST", "ASSC", "PROF"), "salary": i64()})
    p.event("student_snapshot", doc="State at N: address, major, class and GPA",
            cols={"student_id": ref("student"), "city": text(), "state": text(), "zip": text(),
                  "major": cat("IS", "FIN", "ACCT"), "class": cat("FR", "SO", "JR", "SR"),
                  "gpa_tenths": i64(doc="StdGPA × 10")})
    p.event("offering_snapshot", doc="State at N: the assigned teacher, NULL when unassigned",
            cols={"offering_id": ref("offering"), "faculty_id": opt(ref("faculty"))})
