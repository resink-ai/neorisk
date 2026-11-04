"""University: Mannino's textbook sample. Students enrol in course offerings and get a grade;
faculty teach the offerings and report to a supervisor. Stage 1, schema only: the events are
ingested from the Spider2 tables (docs/research/spider2/university.md).

Only faculty hire dates are real times. Enrollment happens at its offering's term start and the
grade at its term end, by a term-calendar rule. Rank, salary, class and GPA are snapshot
columns at N = 2010-08-31. Grades and GPAs travel as integers of tenths.
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
             doc="created_at = FacHireDate; rank and salary are snapshot columns",
             cols={"ext_id": text(doc="FacNo"), "first_name": text(), "last_name": text(),
                   "city": text(), "state": text(), "dept": cat("MS", "FIN", "CS"),
                   "supervisor_id": opt(ref("faculty")), "zip": text()})
    p.entity("student", key="student_id",
             doc="Created at the catalog start by rule; class and GPA are snapshot columns",
             cols={"ext_id": text(doc="StdNo"), "first_name": text(), "last_name": text(),
                   "city": text(), "state": text(), "zip": text(),
                   "major": cat("IS", "FIN", "ACCT")})
    p.entity("offering", key="offering_id", doc="Created at its term start by rule",
             cols={"ext_id": text(doc="OfferNo"), "course_id": ref("course"),
                   "term": cat("FALL", "WINTER", "SPRING", "SUMMER"), "year": i64(),
                   "location": text(), "time": text(doc="'10:30 AM', verbatim"),
                   "faculty_id": opt(ref("faculty")), "days": text()})
    p.event("student_enrolled", doc="At the offering's term start (a rule)",
            cols={"student_id": ref("student"), "offering_id": ref("offering")})
    p.event("grade_recorded", doc="At the offering's term end (a rule)",
            cols={"student_id": ref("student"), "offering_id": ref("offering"),
                  "grade_tenths": i64(doc="EnrGrade × 10")})
    p.event("faculty_snapshot", doc="Rank and salary at N",
            cols={"faculty_id": ref("faculty"), "rank": cat("ASST", "ASSC", "PROF"),
                  "salary": i64()})
    p.event("student_snapshot", doc="Class and GPA at N",
            cols={"student_id": ref("student"), "class": cat("FR", "SO", "JR", "SR"),
                  "gpa_tenths": i64(doc="StdGPA × 10")})
