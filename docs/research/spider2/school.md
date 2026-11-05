# school_scheduling (Spider 2.0-lite): reverse-engineered event log

Source: `data/spider2/school_scheduling.sqlite` (200 KB), opened read-only. `scripts/school/rq.py` copies the file into an in-memory SQLite and runs named blocks; the file itself is never written.

Every number below comes from one of these scripts:
- a named query in `scripts/school/q*.sql`;
- `profile.py` (storage classes, NULL / `''` / `'\N'`, whitespace, min, max per column);
- `coltypes.py` (results types, using the repo's rule in `apps/dataset/src/dataset/tables.py`);
- `f1_floats.py` (are the REAL columns short decimals?);
- `gold_check.py` (a query's answer against a gold CSV, as a multiset).

The raw outputs are in `scripts/school/out_*.txt`. A reference such as `[q4:status_grade_rule]` means file `q4_proofs.sql`, block `-- name: status_grade_rule`. Gold files are in `scripts/school/gold/`.

## 0. What this catalog is

- **Dataset.** The **School Scheduling** sample database from John L. Viescas and Michael J. Hernandez, *SQL Queries for Mere Mortals*. The evidence:
  - It has the book's cast: student and staff names such as Viescas, Hallmark, Patterson, Sheskey and Rosales III, which also appear in BowlingLeague and EntertainmentAgency.
  - It has the same placeholder joke: student 1019 is "Daffy Dumbwit", with GPA 0, NULL major and no classes [q4:student_major_null].
  - It has the same Access-port habits: `BOOLEAN NOT NULL DEFAULT 0` and AUTOINCREMENT ids starting at book-specific seeds (Staff 98005.., Students 1001.., Class_Rooms 1131..) [q1:sqlite_sequence].
- **Date shift.** There are two terms: classes start 2017-09-11/12/16 (fall) and 2018-01-15/16/20 (spring) [q2:class_start_dates]. Staff were hired 1982-11-20 .. 1992-02-10 [q2:staff_hired]. As in EntertainmentAgency, only the activity dates look moved forward, presumably by the 4th edition. **Unverified.**
- **Row counts** [profile]: Classes 147, Faculty_Classes 145, Student_Schedules 120, Faculty_Subjects 110, Faculty_Categories 76, Subjects 56, Class_Rooms 47, Staff 27, Faculty 24, Categories 19, Students 19, Majors 7, Buildings 6, Departments 5, Student_Class_Status 3. Total 811.
- **System table.** `sqlite_sequence` has 7 rows, and each `seq` equals its table's max id (Staff 98,064, Classes 6,600, Class_Rooms 3,455, Students 1,019, Subjects 56, Departments 5, Student_Class_Status 3) [q1:sqlite_sequence]. It is not data.
- **Licence.** Unstated. These are the book's companion sample files.
- **Nature.** **Course data**, hand-made. The spring timetable is a copy of the fall one (§4).

## 0.1 How Spider 2.0 uses it

| id | analysis | gold SQL? | gold value | reproduced |
|---|---|---|---|---|
| local130 | last names of students who completed (ClassStatus = 2) an English class, with a quintile from "share of completions with grade ≥ mine", First..Fifth | no (CSV `_a`) | 18 rows: Bishop 98.07 First … Lum 67.19 Fifth | ✔ 18 of 18, equal as a multiset [q3:local130, out_gold_check.txt]. "English" is `Subjects.CategoryID = 'ENG'`; 18 completions by 18 distinct students [q3:english_completions] |

local130 needs `Grade` exactly (it ranks on it) and `ClassStatus`, so the completion lifecycle (§2) must rebuild both exactly.

## 1. Inventory, keys, joins

Every declared PK is unique, and rowid order equals PK order everywhere [profile]. 19 declared and implied FKs resolve with 0 orphans [q1:fk_orphans].

| Table | Rows | Key | Kind |
|---|---:|---|---|
| Buildings | 6 | BuildingCode (text) | lookup |
| Class_Rooms | 47 | ClassRoomID 1131..3455 → BuildingCode | lookup |
| Departments | 5 | DepartmentID; DeptChair → Staff | lookup |
| Categories | 19 | CategoryID (text, e.g. `ENG`) → DepartmentID | lookup |
| Subjects | 56 | SubjectID; SubjectCode unique; SubjectPreReq → **SubjectCode** (text) | catalog |
| Majors | 7 | MajorID | lookup |
| Student_Class_Status | 3 | 1 Enrolled, 2 Completed, 3 Withdrew | lookup |
| Staff | 27 | StaffID 98005..98064 | party (DateHired) |
| Faculty | 24 | StaffID → Staff (1:1 subtype; Position = 'Faculty' in 24 of 24) | party extension |
| Faculty_Categories / Faculty_Subjects | 76 / 110 | (StaffID, CategoryID) / (StaffID, SubjectID) + ProficiencyRating | links |
| Classes | 147 | ClassID 1000..6600 → SubjectID, ClassRoomID | sections (StartDate, StartTime) |
| Faculty_Classes | 145 | (ClassID, StaffID); one teacher per class | link |
| Students | 19 | StudentID 1001..1019 → StudMajor | party |
| Student_Schedules | 120 | (StudentID, ClassID) → ClassStatus; + Grade | activity (no own time) |

No table is a copy of another, and none is fully derived.

Coverage [q1:coverage, q1:staff_not_faculty, q4:classes_without_faculty]:
- Only 32 of 147 classes have students.
- 2 classes have no teacher: 1642 and its spring twin 4642, both subject 29.
- 3 staff are not faculty: the Registrar, a Secretary and the Graduate Advisor.
- 1 faculty member teaches nothing, and 1 student has no classes.
- Unused: 4 subjects, 8 rooms, 1 building, 3 categories.

Consistency [q1:class_teacher_subject_consistency, q4:teacher_lacking_subject, q1:fac_subjects_categories_consistency]:
- A class's teacher lists the class's subject in Faculty_Subjects in 140 of 145 rows. The 5 exceptions are 2 fall/spring pairs plus 1 more.
- Every Faculty_Subjects row's category is in Faculty_Categories, 110 of 110.
- Every department chair is faculty, 5 of 5 [q1:chairs_are_faculty].
- `SubjectCode`'s prefix equals `CategoryID` in 55 of 56. The exception is subject 28: `CIS 142` filed under CSC [q4:subject_code_mismatch].

Room ids fall in per-building ranges (AS 1514–1627, LB 1131–1231, TB 1639–1642; CC and IB interleave) [q1:classroom_id_encodes_building]. Keep the ids verbatim; nothing derives from them.

## 2. Event catalogue

The only times are `Classes.StartDate` + `StartTime` (a section's first meeting) and `Staff.DateHired`. There is no enrolment, completion, withdrawal or grading date. So the student lifecycle is real, but all its times come from rules.

The lifecycle is clean and term-aligned [q4:status_vs_term]:
- Fall-2017 enrolments end as Completed (68) or Withdrew (2).
- Spring-2018 enrolments are all still Enrolled (50).
- Grade is > 0 exactly when the status is Completed, 120 of 120. The 52 non-completed rows all have Grade 0.0 [q4:status_grade_rule].

| # | Event | Owner | Time | Attributes | Source rows | Count |
|---|---|---|---|---|---|---:|
| E1 | `student_enrolled` | student (ord = ClassID) | the class's start, StartDate + StartTime (rule: no enrolment date) | class_id (ref classes) | Student_Schedules | 120 |
| E2 | `class_completed` | student (ord = ClassID) | **T_end = 2018-01-14 00:00**, the day before the spring term (rule) | class_id (ref), grade (f64) | rows with ClassStatus 2 | 68 |
| E3 | `class_withdrawn` | student (ord = ClassID) | T_end (rule) | class_id (ref) | rows with ClassStatus 3 | 2 |

**Business events: 190.** In addition there are snapshot events at N for the snapshot columns: `students_snapshot` 19, `staff_snapshot` 27 and `faculty_snapshot` 24.

Entities (14 tables, 691 rows):

| Entity | Rows | created_at | natural? |
|---|---:|---|---|
| staff | 27 | `DateHired` | natural |
| faculty | 24 | the staff row's DateHired | natural (1:1) |
| classes | 147 | StartDate + StartTime | natural (the section's first meeting) |
| faculty_classes | 145 | the class's created_at; ext_id `"ClassID/StaffID"` | rule |
| buildings, class_rooms, departments, categories, subjects, majors, student_class_status | 6, 47, 5, 19, 56, 7, 3 | T0 = 2017-09-11 00:00, the first class date | rule |
| faculty_categories, faculty_subjects | 76, 110 | T0 | rule |
| students | 19 | T0 (all exist at term start; 1019 has no classes) | rule |

**Snapshot columns** (values known only at N, so they travel on `<entity>_snapshot` at N):
- `Students.StudGPA`. It is not a function of the grades: it matches the mean of completed grades within 0.01 for 0 of 18 students [q4:gpa_not_derived]. For example, 1012 has GPA 89.5 but mean 70.56 [q2:gpa_vs_grades]. It is a stored lifetime figure.
- `Staff.Salary`, and `Faculty.Title`, `Status` (including "On Leave") and `Tenured`: these are current state, so they are snapshot columns under the contract's "when in doubt" rule.

What is **not** an event, and why:
- **Class scheduling** is not an event. A class is an entity created at its first meeting. A separate `class_scheduled` would need a scheduling date the source lacks.
- **"Still enrolled"** (status 1) is the absence of E2 and E3 at N, so it needs no event.
- **Teaching assignments and proficiencies** have no time. They are static links.

Snapshot **N = 2018-01-20**, the last class start.

## 3. Rebuild rules and blockers to an exact round trip

1. **Student_Schedules from the lifecycle** [q4:status_grade_rule, q4:status_vs_term]:
   - ClassStatus = 2 when E2 exists, 3 when E3 exists, and 1 otherwise.
   - Grade = E2.grade, else 0.0.

   This rule is exact on 120 of 120 rows, because every non-completed row has Grade exactly 0.0.
2. **No derived tables.** The spring classes are mostly copies of fall (§4), but 15 spring classes have no fall twin [q5:spring_without_twin]. Copying would also tie the build to a generator quirk, so carry all 147 classes.
3. **Times.** Classes.StartDate is `YYYY-MM-DD` and StartTime is `HH:MM:SS`, 147 of 147 [q2:class_formats]. Staff.DateHired is `YYYY-MM-DD` [q2:staff_hired]. The view formats `created_at` back with `%Y-%m-%d` and `%H:%M:%S`. The rule times T0 and T_end never reach a results column.
4. **Floats** [f1_floats]. All REAL values round-trip through their shortest repr. Carry them as `f64` verbatim:
   - Grade (120 values): 0, 1 or 2 decimals;
   - StudGPA (19): up to 3 decimals, e.g. 74.465;
   - Salary (27): whole numbers stored as REAL;
   - ProficiencyRating (110): 8.0, 9.0, 10.0.

   Salary and ProficiencyRating are float64 in results because of REAL affinity [coltypes], so `i64` would need a `CAST … AS DOUBLE` in the view. `f64` is simpler.
5. **Text keys and refs by code.**
   - `BuildingCode` and `CategoryID` are text keys.
   - `Subjects.SubjectPreReq` references `SubjectCode`, not SubjectID, and is NULL in 47 of 56 [profile, q1:prereqs]. Carry it as `opt(text)` verbatim, not as a ref: a ref resolves through `ext_id` = SubjectID.
   - `Departments.DeptChair` is a ref to staff.
6. **NULL vs empty.** No `''` and no `'\N'`. The only NULLs are SubjectPreReq (47) and StudMajor (1, student 1019) [profile]. `SubjectDescription` is 81–307 characters [q5:description_length]; keep it byte-exact. No mixed columns [coltypes].
7. **Booleans** (ElevatorAccess, SiteParkingAvailable, PhoneAvailable, Tenured, the six `*Schedule` day flags) hold integers 0/1, so they are int64 in results. Carry them as `i64`.

**Verdict:** exact round trip, yes. The lifecycle rule is proven on 120 of 120 rows. Every invented time (enrolment at class start, completion and withdrawal at T_end, lookups at T0) is a rule that stays out of the results.

## 4. Measured quirks

- **The spring timetable is the fall one plus 3000.** 66 of 81 spring classes have a twin at ClassID − 3000 that is identical in subject, room, credits, start time, duration and all six day flags [q5:spring_is_fall_plus_3000, q5:twin_differences]. The date is +126 days in 64 of them. The other 2 swap with the Saturday slot: 09-12 → 01-20 (+130) and 09-16 → 01-15 (+121) [q5:twin_date_offsets]. 64 of the 80 spring teaching rows keep the fall teacher [q5:faculty_twins]. No student takes a class and its twin [q5:enrolment_pattern].
- **Room double-booking.** 11 pairs of classes share a room on overlapping days and times, mostly in room 3346 and repeated in both terms [q4:room_conflict_pairs]. 3 student pairs have overlapping class times [q2:student_time_clash].
- **Credits ≠ contact hours.** 5-credit classes meet anywhere from 1 day × 280 min to 5 days × 50 min [q2:credits_vs_days]. 62 of 147 classes are Mon–Fri at 50 minutes [q2:days_pattern].
- **GPA contradicts the grades** (§2). For example, 1005 has GPA 72.2 but a completed mean of 84.7.
- **Placeholders.** Student 1019 "Daffy Dumbwit" has GPA 0, no major and no classes. There are also a teacher-less class pair and 3 non-faculty staff (§1).
- **The one mis-filed subject:** `CIS 142` under category CSC [q4:subject_code_mismatch].

## 5. Distributions to fit (stage 2)

| Quantity | Value |
|---|---|
| enrolments per student | 7 for 16 students, 4 for 2. Fall: 3–4 completed; the 2 four-class students also withdrew from 1. Spring: 3–4 enrolled, or 0 for those 2 [q2:enrolments_per_student] |
| outcome | completed 68 of 70 fall enrolments (97.1%), withdrew 2 [q4:status_vs_term] |
| grade (completed) | 65.8–99.83, mean 81.81. 5-point bands from 65: 12, 12, 7, 4, 15, 11, 7, so bimodal [q4:grades_dist, q4:grade_moments] |
| class size (with students) | 1–10, mode 3 (12 classes) [q4:class_size] |
| class start time | 07:00–18:00, on the hour or half hour; 08:00–11:00 and 13:00 dominate [q4:start_times] |
| meeting pattern | Mon–Fri 50 min (62), MW 110/140 min (22), MWF (12), TTh (12) … [q2:days_pattern] |
| duration | 50 (100), 140 (30), 110 (12), 80 (3), 280 (2) [q2:durations] |
| proficiency | 8, 9, 10, nearly uniform (37 / 40 / 33) [q2:proficiency] |

Volume is tiny (190 business events). Stage 2's value here is the lifecycle shape (enrol → complete or withdraw, with a grade), not volume.

## 6. simkit mapping sketch

```python
p.entity("buildings", key="building_id", cols={"ext_id": text(), "building_name": opt(text()), "number_of_floors": opt(i64()),
         "elevator_access": i64(), "site_parking_available": i64()})
p.entity("class_rooms", key="class_room_id", cols={"ext_id": text(), "building_id": opt(ref("buildings")), "phone_available": i64()})
p.entity("staff", key="staff_id", cols={"ext_id": text(), "first_name": opt(text()), ..., "position": opt(text())})   # created_at = DateHired
p.entity("departments", key="department_id", cols={"ext_id": text(), "dept_name": opt(text()), "dept_chair": opt(ref("staff"))})
p.entity("categories", key="category_id", cols={"ext_id": text(), "description": opt(text()), "department_id": opt(ref("departments"))})
p.entity("subjects", key="subject_id", cols={"ext_id": text(), "category_id": opt(ref("categories")), "subject_code": opt(text()),
         "subject_name": opt(text()), "subject_prereq": opt(text(doc="a SubjectCode")), "subject_description": opt(text())})
p.entity("faculty", key="faculty_id", cols={"ext_id": text(), "staff_id": ref("staff")})          # Title/Status/Tenured: snapshot
p.entity("classes", key="class_id", cols={"ext_id": text(), "subject_id": opt(ref("subjects")), "class_room_id": opt(ref("class_rooms")),
         "credits": opt(i64()), "duration": opt(i64()), "monday": i64(), ..., "saturday": i64()})  # created_at = first meeting
p.entity("students", key="student_id", cols={"ext_id": text(), "first_name": opt(text()), ..., "major_id": opt(ref("majors"))})
# + majors, student_class_status, faculty_categories, faculty_subjects (proficiency f64), faculty_classes (link entities)
p.event("student_enrolled", cols={"student_id": ref("students"), "class_id": ref("classes")})
p.event("class_completed", cols={"student_id": ref("students"), "class_id": ref("classes"), "grade": f64()})
p.event("class_withdrawn", cols={"student_id": ref("students"), "class_id": ref("classes")})
# snapshot columns at N: students.stud_gpa (f64); staff.salary (f64); faculty.title, status (text), tenured (i64)
```

Ingest:
- `-- event: student_enrolled owner=student_id ord=class_id`: Student_Schedules ⋈ Classes, `event_time = StartDate || ' ' || StartTime`, ORDER BY StudentID, ClassID.
- `class_completed` and `class_withdrawn`: `event_time = '2018-01-14 00:00:00'`, filtered on ClassStatus.
- Classes: `created_at = StartDate || ' ' || StartTime`.

build.sql:
- `Student_Schedules` = E1 LEFT JOIN E2 LEFT JOIN E3, with ClassStatus and Grade as in §3.1.
- `Classes.StartDate` and `StartTime` are formatted from `created_at`.
- `Faculty` = entity + snapshot.
- `Students.StudGPA` comes from the snapshot.
- Everything else is a straight entity projection.

Stage 2 owners:
- **student** (enrols in 3–4 sections per term, completes with p ≈ 0.97, draws a grade);
- a **registrar** source that creates each term's sections (and could reproduce the copy-forward timetable deliberately).

## 7. Open questions and risks

- **Rule times dominate.** Enrolment at the class start and completion at 2018-01-14 are inventions. A sim fitting "time to completion" would fit the rule. Say so in CONTEXT.md, as for Airlines' check-ins.
- **Withdrawal time.** Two withdrawals are put at T_end. A mid-term date would be more realistic, but nothing supports any specific date.
- **Snapshot-column calls.** StudGPA is clearly snapshot. Treating Salary and faculty Title/Status/Tenured as snapshot follows the "when in doubt" rule; they could equally ride on creation. Either is exact.
- **Edition and licence** are unverified (§0).
- **`SubjectPreReq` as text.** If a later pack wants prerequisite graphs, it needs a code-keyed ref, which the convention (refs by ext_id) does not provide.

**Summary**
- Exact round trip: yes. The status and grade lifecycle rule holds on 120 of 120 rows; floats are verbatim f64; no table is derived.
- Dataset name: `school`.
- Event types 3 (`student_enrolled`, `class_completed`, `class_withdrawn`), plus 3 snapshot events; entities 14.
- Event shape: mostly imposed. The enrol → complete/withdraw lifecycle is real, but every one of its times is a rule. The bulk (691 of 811 rows) is static catalogue and links.
- Hardest blocker: there is no enrolment, completion or withdrawal date. Every business event's time is a rule (the class start, and T_end = 2018-01-14), and StudGPA has to be a snapshot because it contradicts the grades.
