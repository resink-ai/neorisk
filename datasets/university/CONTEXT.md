# university

## What this is

A university's course records: students enrol in course offerings and get a grade; faculty teach the offerings and report to a supervisor.

Version `v1`, kind `spider2`. The input is one ordered event log of 145 events; the output is the 5 source tables, rebuilt exactly, and the answer to 1 saved Spider 2.0 question.

## Raw data

`education_business.sqlite` (the 5 `university_*` tables, 76 rows). Hand-made sample data from Michael Mannino's textbook *Database Design, Application Development, and Administration*, with two extra faculty (JOHN DOE, JANE SMITH); textbook material, licence unstated.

The only real time is `FacHireDate` (a date, read as UTC midnight). Every other time is a rule.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/university.md`](../../docs/research/spider2/university.md).

## How the log was made

Courses, faculty, students and offerings are entities. Each enrollment row is two events owned by the student: `student_enrolled` at its offering's term start and `grade_recorded` at its term end, with the grade as an integer of tenths. Faculty address, department, supervisor, rank and salary, student address, major, class and GPA, and each offering's assigned teacher can change over time and the source holds only their latest value, so they travel on `<entity>_snapshot` events at N rather than on creation. A faculty member's creation event is `faculty_hired`, at the hire date. Faculty and student ids stay separate entities: 123456789 is a different person in each table.

`uv run dataset build university` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `course_created` | entity | 7 | `course_id`, `ext_id`, `crs_desc`, `crs_units` |
| `faculty_hired` | entity | 8 | `faculty_id`, `ext_id`, `first_name`, `last_name` |
| `student_created` | entity | 11 | `student_id`, `ext_id`, `first_name`, `last_name` |
| `offering_created` | entity | 13 | `offering_id`, `ext_id`, `course_id`, `term`, `year`, `location`, `time`, `days` |
| `student_enrolled` | business | 37 | `student_id`, `offering_id` |
| `grade_recorded` | business | 37 | `student_id`, `offering_id`, `grade_tenths` |
| `faculty_snapshot` | business | 8 | `faculty_id`, `city`, `state`, `zip`, `dept`, `supervisor_id`, `rank`, `salary` |
| `student_snapshot` | business | 11 | `student_id`, `city`, `state`, `zip`, `major`, `class`, `gpa_tenths` |
| `offering_snapshot` | business | 13 | `offering_id`, `faculty_id` |

## Times set by rule

A quarter calendar gives each term a span: WINTER y-01-01 to y-03-31, SPRING y-04-01 to y-06-30, SUMMER y-07-01 to y-08-31, FALL y-09-01 to y-12-31. Offerings are created, and enrollments happen, at the term start; grades are recorded at the term end. Courses and students are created at the catalog start, 2009-07-01 (the start of Summer 2009, the first term). Snapshots are at N = 2010-08-31, the end of Summer 2010, the last term with an offering. Faculty are created at their hire date. The dates are invented; only the term order within a year matters. `OffTerm` and `OffYear` travel as offering attributes, so they never depend on the calendar.

## Snapshot columns

| Entity | Snapshot event | At (UTC) | Rows | Columns |
|---|---|---|---:|---|
| `faculty` | `faculty_snapshot` | 2010-08-31 00:00:00 | 8 | `city`, `state`, `zip`, `dept`, `rank`, `salary` |
| `student` | `student_snapshot` | 2010-08-31 00:00:00 | 11 | `city`, `state`, `zip`, `major`, `class`, `gpa_tenths` |
| `offering` | `offering_snapshot` | 2010-08-31 00:00:00 | 13 | `faculty_id` |

The counted table leaves out `faculty_snapshot.supervisor_id`: it lists a snapshot's payload minus every ref to its own entity, and the supervisor is a ref to `faculty`. It is a snapshot column too.

| Column | Verdict | Reason |
|---|---|---|
| `course.ext_id` | creation | The source key (`CourseNo`). |
| `course.crs_desc` | creation | The course's title. |
| `course.crs_units` | creation | Fixed with the catalog entry; the source shows no change. |
| `faculty.ext_id` | creation | The source key (`FacNo`). |
| `faculty.first_name` | creation | Given names. |
| `faculty.last_name` | creation | Given names. |
| `faculty.created_at` (`FacHireDate`) | creation | The hire date; it is the event's time. |
| `faculty.city` | snapshot | An address, known only as of the extract. Research kept them on creation; the rubric lists addresses as snapshot. |
| `faculty.state` | snapshot | An address, known only as of the extract. Research kept them on creation; the rubric lists addresses as snapshot. |
| `faculty.zip` | snapshot | An address, known only as of the extract. Research kept them on creation; the rubric lists addresses as snapshot. |
| `faculty.dept` | snapshot | A department assignment can change after the hire; when in doubt, snapshot. Research kept it on creation. |
| `faculty.supervisor_id` | snapshot | The reporting line can change after the hire; when in doubt, snapshot. Research kept it on creation. |
| `faculty.rank` | snapshot | Promotions and raises; the source has only the value at N. |
| `faculty.salary` | snapshot | Promotions and raises; the source has only the value at N. |
| `student.ext_id` | creation | The source key (`StdNo`). |
| `student.first_name` | creation | Given names. |
| `student.last_name` | creation | Given names. |
| `student.city` | snapshot | An address. Research kept them on creation; the rubric lists addresses as snapshot. |
| `student.state` | snapshot | An address. Research kept them on creation; the rubric lists addresses as snapshot. |
| `student.zip` | snapshot | An address. Research kept them on creation; the rubric lists addresses as snapshot. |
| `student.major` | snapshot | A student can change major; when in doubt, snapshot. Research kept it on creation. |
| `student.class` | snapshot | FR/SO/JR/SR advances over time. |
| `student.gpa_tenths` | snapshot | A cumulative value the 37 grades do not explain (2 of 11 match). |
| `offering.ext_id` | creation | The source key (`OfferNo`). |
| `offering.course_id` | creation | An immutable ref: the course the section is of. |
| `offering.term` | creation | The term the section was created for. |
| `offering.year` | creation | The term the section was created for. |
| `offering.location` | creation | The published timetable that defines the section, as in school's classes. |
| `offering.time` | creation | The published timetable that defines the section, as in school's classes. |
| `offering.days` | creation | The published timetable that defines the section, as in school's classes. |
| `offering.faculty_id` | snapshot | The teacher assignment; 2 offerings are still unassigned (NULL), so it is the state at N, not a value fixed at the term start. Research kept it on creation. |

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `university_course` | 7 | 3 | none |
| `university_faculty` | 8 | 11 | none |
| `university_student` | 11 | 9 | none |
| `university_offering` | 13 | 8 | none |
| `university_enrollment` | 37 | 3 | none |

`expected/queries/` holds the answers of the saved questions (`local163`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

The faculty refs `FacSupervisor` and `university_offering.FacNo` are REAL in the source (`654321098.0`); they come back as doubles of the referenced faculty id. Grades and GPAs come back as tenths divided by 10, the same doubles as the source's one-decimal values.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build university             # → $NEORISK_DATA_ROOT/university/v1/ (default data/datasets/)
uv run dataset verify university            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`; this catalog is too small to fit, so it is best replayed as a fixed fixture.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
