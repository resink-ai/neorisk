# University (Spider 2.0-lite, `education_business` `university_*`): reverse-engineered event log

Source: the five `university_*` tables of `data/spider2/education_business.sqlite`, opened read-only. `scripts/university/rq.py` copies the file into an in-memory SQLite and runs named blocks; the file itself is never written. The other catalogs in the file are AtliQ ([atliq.md](atliq.md)), Parch & Posey ([parchposey.md](parchposey.md)) and `StaffHours` + `SalaryDataset` ([edu_misc.md](edu_misc.md)).

Every number below comes from a named block of `scripts/university/q1_all.sql`; the raw output is `scripts/university/out_q1_all.txt`. A reference such as `[q1:fk_orphans]` means that block. Gold files are in `scripts/university/gold/`. The tables are tiny (76 rows), so I read every row as well (§1).

## 0. What this catalog is

- **Dataset.** This is the **university database from Michael Mannino's textbook** *Database Design, Application Development, and Administration* (McGraw-Hill). Its tables are Student, Faculty, Offering, Course and Enrollment, which Spider prefixes with `university_`. The evidence:
  - Mannino's sample people are here: HOMER WELLS, BOB NORBERT, CANDY KENDALL, LEONARD VINCE, VICTORIA EMMANUEL, LEONARD FIBON, NICKI MACON, CRISTOPHER COLAN and JULIA MILLS.
  - Mannino's 9-digit ids are here: 123456789, 543210987.
  - So are his courses (IS320 FUNDAMENTALS OF BUSINESS PROGRAMMING, IS480 FUNDAMENTALS OF DATABASE MANAGEMENT, FIN300) and his offerings 1111–9876 in BLM rooms.
  - Mannino's FacNo `098765432` appears as **98765432**: the INTEGER load dropped its leading zero [q1:faculty_no_leading_zero]. That is also why faculty rowid order has 1 descending pair: the source was sorted as text [q1:rowid_order].
- **Differences from the textbook editions I know** (unverified). The years are 2009/2010; earlier editions use 2005/2006. There are also two extra faculty, **JOHN DOE** (CS, 2005) and **JANE SMITH** (CS, 2007). They may come from a later edition or a course adaptation. Neither teaches an offering [q1:unused_parents].
- **Row counts** [q1:row_counts]: enrollment 37, offering 13, student 11, faculty 8, course 7. The total is 76.
- **Licence.** Unstated. These are textbook sample data.
- **Nature.** **Hand-made course data.** The names are fictitious; Washington-state cities and zip codes are used.

## 0.1 How Spider 2.0 uses it

| id | asks | gold SQL? | gold answer | reproduced |
|---|---|---|---|---|
| local163 | faculty whose salary is closest to their rank's average: rank, first and last name, salary | yes | ASSC LEONARD FIBON 70000; ASSC JULIA MILLS 75000; ASST CRISTOPHER COLAN 40000; PROF JANE SMITH 110000 | ✔ exactly [q1:gold_local163] |

- The ASSC rank ties: the average is 72,500, and both 70,000 and 75,000 are 2,500 away [q1:rank_salary].
- The PROF answer depends on the extra JANE SMITH row. Without her, the PROF average would be 92,500, and the answer would be NICKI MACON (65,000, 27,500 away) or VICTORIA EMMANUEL (120,000, 27,500 away) in a tie.

So the rebuild must keep `FacRank`, `FacSalary` and every faculty row exactly.

## 1. Inventory, keys, joins

No PK or FK is declared. All keys below are verified unique, and all joins resolve with 0 orphans [q1:key_uniqueness, q1:fk_orphans].

| Table | Rows | Key | Kind |
|---|---:|---|---|
| university_enrollment | 37 | (OfferNo, StdNo) | activity: a student takes an offering and gets a grade; no time |
| university_offering | 13 | OfferNo → CourseNo, FacNo (REAL, 2 NULL) | schedule: term, year, room, time, days |
| university_student | 11 | StdNo (INTEGER, 9 digits) | party |
| university_faculty | 8 | FacNo (INTEGER); FacSupervisor (REAL, 2 NULL) self-FK | party / org chart |
| university_course | 7 | CourseNo (text) | catalog |

Joins and coverage:
- enrollment → offering and student; offering → course; offering.FacNo → faculty (11 non-null); FacSupervisor → faculty (6 non-null): all 100% [q1:fk_orphans].
- **Unused parents** [q1:unused_parents]:
  - 5 offerings have no enrollment: 1111, 2222, 3333, 4444 and 8888, all Summer 2009, Summer 2010, Spring 2010 or Winter 2010 offerings of IS320/IS460;
  - 1 course is never offered (IS470);
  - 2 faculty teach nothing (DOE, SMITH).

  Every student is enrolled.
- **Faculty ids collide with student ids.**
  - 876543210 is CRISTOPHER COLAN in both tables, the same person: a faculty member who is also an SR student, as in Mannino.
  - 123456789 is JOHN DOE (faculty) and HOMER WELLS (student), a different person [q1:faculty_also_student].

  So the two id spaces must stay separate entities.
- **No copies or derived tables.** `StdGPA` is not derived from the enrollment grades: only 2 of 11 students are within 0.05 of their mean grade [q1:gpa_vs_grades, q1:gpa_equals_avg].
- Offerings, students and enrollments are in key order by rowid. Faculty is in text order of the original zero-padded ids [q1:rowid_order].

## 2. Event catalogue

Nothing here has a natural event time except `FacHireDate`. Enrollment is the only activity. It is keyed to an offering, whose term and year give a **rule** time.

**Term rule** (Mannino's quarter system: FALL, WINTER, SPRING, SUMMER):

| term | start | end |
|---|---|---|
| WINTER y | y-01-01 | y-03-31 |
| SPRING y | y-04-01 | y-06-30 |
| SUMMER y | y-07-01 | y-08-31 |
| FALL y | y-09-01 | y-12-31 |

The dates are invented. Only the order of terms within a year matters: Winter < Spring < Summer < Fall.

| # | Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `student_enrolled` | student (ord = OfferNo) | rule: the offering's term start | offering_id (ref) | enrollment | 37 |
| E2 | `grade_recorded` | student (ord = OfferNo) | rule: the offering's term end | offering_id (ref), grade (tenths, i64) | enrollment | 37 |
| S1 | `faculty_snapshot` | faculty | N | FacRank, FacSalary | faculty | 8 |
| S2 | `student_snapshot` | student | N | StdClass, StdGPA | student | 11 |

**Total events: 93**: 74 business events and 19 snapshot events. All their times are set by rule.

Entities (4 tables, 39 rows):
- **course** (7). `created_at` is the catalog start by rule, 2009-07-01 (the start of the first term, Summer 2009) [q1:terms].
- **faculty** (8). `created_at` = **FacHireDate**, the one natural time (1996-05-01..2007-08-20). Attributes: names, city, state, dept, zip text and `FacSupervisor` as `opt(ref(faculty))`. Rank and salary go to S1.
- **student** (11). `created_at` is the catalog start by rule. Attributes: names, city, state, zip and major. Class and GPA go to S2.
- **offering** (13). `created_at` is its term start by rule. Attributes: course (ref), OffTerm, OffYear, OffLocation, OffTime, `FacNo` as `opt(ref(faculty))` and OffDays.

**Snapshot columns, with reasons:**
- `StdGPA`: a cumulative value that the 37 grades do not explain (2 of 11 match).
- `StdClass`: FR/SO/JR/SR changes over time.
- `FacRank` and `FacSalary`: promotions and raises. The source has only the value at N.

All are kept out of the creation events, so no event carries a value from its future.

What is **not** an entity: **departments** (`FacDept` MS/FIN/CS) and **majors** (IS/FIN/ACCT). Both are flat text with no table.

Snapshot **N = 2010-08-31**, the rule end of Summer 2010, the latest term with an offering [q1:terms]. No Fall 2010 offering exists. N is a rule.

## 3. Rebuild rules and blockers to an exact round trip

1. **REAL ids.**
   - `FacSupervisor` (6 values) and `offering.FacNo` (11 values) are stored as REAL, for example `654321098.0`; the NULLs are real NULLs [q1:typeof_columns]. This is pandas' NaN → float artefact.
   - The faculty key `FacNo` itself is INTEGER.
   - The view must write the refs back as `CAST(ext_id AS DOUBLE)`. They compare by value anyway (654321098 = 654321098.0), and the declared affinity REAL maps to float64, so this is not a mixed column.
2. **Grades.**
   - `EnrGrade` (2.0–4.0) and `StdGPA` (2.2–4.0) all have 1 decimal [q1:grade_decimals].
   - Carry grades as integer tenths and rebuild them as `n / 10.0`. In IEEE that is the same double as the literal: `33/10.0 = 3.3`. Or carry `f64` verbatim.
3. **Text.**
   - `FacHireDate` is `YYYY-MM-DD`: rebuild it from `created_at` with `%Y-%m-%d`.
   - `OffTime` (`10:30 AM`, `1:30 PM`, without zero padding) and both zip columns (`98111-9921`) are text. Carry them verbatim.
   - All names are upper case, with no stray whitespace [q1:whitespace_case].
4. **OffTerm and OffYear** are carried as offering attributes, not recomputed from the rule time. That keeps them exact whatever the term calendar is.
5. **NULLs.** The only NULLs are 2 FacSupervisor (EMMANUEL, MACON, the two heads) and 2 offering.FacNo (1111, 2222, both unassigned) [q1:typeof_columns]. There are no empty strings.
6. **Rows without time.** Every event time comes from a rule (§2). Only faculty creation is natural.

**Verdict:** an exact round trip is feasible. The catalog is reference data with a single tiny activity table, and every value is verbatim or a tenths integer.

## 4. Measured quirks

- **The leading zero is lost** on faculty 098765432, both in `university_faculty` and in `university_offering.FacNo` and `FacSupervisor` (consistently, so joins still work) [q1:faculty_no_leading_zero, q1:fk_orphans].
- **Id collisions across roles**: COLAN is both faculty and student; DOE and WELLS share 123456789 [q1:faculty_also_student].
- **GPA is not computed from the grades** [q1:gpa_vs_grades]. ROBERTO MORALES has GPA 2.5 but grades averaging 3.65; CRISTOPHER COLAN has GPA 4.0 but averages 3.25. The tables were typed by hand independently.
- **All courses are 4 units**, so a units-weighted GPA would equal the plain mean anyway.
- **Enrollment falls in only 3 terms:** Fall 2009 (12), Winter 2010 (9) and Spring 2010 (16). The two Summer terms and two of the Winter/Spring offerings are empty [q1:enrollment_by_term].
- **No timetable clashes:** no student takes two offerings with the same term, days and time [q1:student_double_booking].
- **Salary versus rank is not monotone.** PROF NICKI MACON earns 65,000, below both ASSCs (70,000 and 75,000) [q1:rank_salary]. Hire dates span 1996–2007, all before the first offering in 2009 [q1:hire_vs_offering].

## 5. Distributions to fit (stage 2)

The data are too small to fit anything beyond a lookup. For the record:

| Quantity | Value |
|---|---|
| enrollments per offering | 0 (5 offerings), 2, 2, 3, 5, 6, 6, 6, 7 [q1:enrollments_per_offering] |
| enrollments per student | 2–5 (mean 3.36) [q1:gpa_vs_grades, q1:grade_mean] |
| grade | 2.0–4.0 in tenths, mean 3.257 [q1:grade_decimals, q1:grade_mean] |
| salary by rank | ASST 35k–55k, ASSC 70k–75k, PROF 65k–120k [q1:rank_salary] |
| terms | 5 (term, year) cells with offerings [q1:terms] |

A stage-2 generator should treat this as a **fixed fixture**, the same rows replayed, rather than something to sample. Any synthetic version is a new design, not a fit.

## 6. simkit mapping sketch

```python
p.entity("courses", key="course_key", cols={"ext_id": text(doc="CourseNo"), "crs_desc": text(), "crs_units": i64()})
p.entity("faculty", key="faculty_key", doc="created_at = FacHireDate; rank and salary are snapshot columns",
         cols={"ext_id": i64(doc="FacNo"), "first_name": text(), "last_name": text(), "city": text(), "state": text(),
               "dept": cat("MS", "FIN", "CS"), "supervisor_id": opt(ref("faculty")), "zip": text()})
p.entity("students", key="student_key", doc="created at the catalog start by rule; class and GPA are snapshot columns",
         cols={"ext_id": i64(doc="StdNo"), "first_name": text(), "last_name": text(), "city": text(), "state": text(),
               "zip": text(), "major": cat("IS", "FIN", "ACCT")})
p.entity("offerings", key="offering_key", doc="created at its term start by rule",
         cols={"ext_id": i64(doc="OfferNo"), "course_id": ref("courses"), "term": cat("FALL", "WINTER", "SPRING", "SUMMER"),
               "year": i64(), "location": text(), "time": text(), "faculty_id": opt(ref("faculty")), "days": text()})
p.event("student_enrolled", cols={"student_id": ref("students"), "offering_id": ref("offerings")})
p.event("grade_recorded", cols={"student_id": ref("students"), "offering_id": ref("offerings"), "grade_tenths": i64()})
p.event("faculty_snapshot", cols={"faculty_id": ref("faculty"), "rank": cat("ASST", "ASSC", "PROF"), "salary": i64()})
p.event("student_snapshot", cols={"student_id": ref("students"), "class": cat("FR", "SO", "JR", "SR"), "gpa_tenths": i64()})
```

Ingest:
- The term rule is a `CASE OffTerm` over `OffYear`.
- `student_enrolled owner=student_id ord=offering_ext`, ORDER BY OfferNo, StdNo.
- `grade_recorded`: the same, at the term end.
- Snapshots at N, ORDER BY key.

`build.sql`:
- `university_enrollment`: the offering ext_id, the student ext_id, and `grade_tenths/10.0` from E2. E1 is used only for existence; it gives the same 37 pairs.
- `university_faculty`: the entity view ⋈ S1, with `CAST(supervisor ext_id AS DOUBLE)` and `strftime(created_at, '%Y-%m-%d') AS FacHireDate`.
- `university_offering`: the entity view, with `CAST(faculty ext_id AS DOUBLE)`.
- `university_student`: the entity view ⋈ S2, with `gpa_tenths/10.0`.
- `university_course`: the entity view.

Owners: student (enrolment), faculty (teaching). There is no request/reply.

## 7. Open questions and risks

- **Which Mannino edition, and who added DOE and SMITH?** This is unverified. The local163 gold relies on SMITH, so keep the rows as they are, whatever their origin.
- **The term calendar is invented.** Every event time is a rule, so stage 2 must not learn timing from this catalog.
- **The snapshot classification** of rank, salary, class and GPA is my call, following "when in doubt, snapshot". An alternative is to keep them on creation. That would be simpler, but it puts a 2010 salary on a 1996 hire event.
- **This could be folded** into a combined `education_business` dataset with the other three catalogs. That is not recommended: they share nothing.

---

- Exact round trip: **yes**. Every value is verbatim, or a tenths integer for the grades and GPA; the REAL-typed faculty refs are rebuilt as doubles.
- Proposed dataset name: **`university`**.
- 4 event types (`student_enrolled`, `grade_recorded`, plus the `faculty_snapshot` and `student_snapshot` snapshots; 93 events) and 4 entities (courses 7, faculty 8, students 11, offerings 13).
- Event shape: **mostly imposed**. Only faculty hire dates are natural; enrolment and grade times come from a term-calendar rule.
- Hardest blocker: there is no real time anywhere except hire dates, so the term calendar and N are invented. The rest is trivial.
