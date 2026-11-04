# school

## What this is

A school's timetable over two terms: students enrol in class sections, then complete them with a grade or withdraw; staff teach classes in rooms, by subject and category.

Version `v1`, kind `spider2`. The input is one ordered event log of 951 events; the output is the 15 source tables, rebuilt exactly, and the answer to 1 saved Spider 2.0 question.

## Raw data

`school_scheduling.sqlite`, 15 tables. The School Scheduling sample database from John L. Viescas and Michael J. Hernandez, *SQL Queries for Mere Mortals*: hand-made course data. The licence is unstated; the files ship with the book for its readers.

Classes start in fall 2017 (2017-09-11, 12 and 16) and spring 2018 (2018-01-15, 16 and 20); staff were hired 1982–1992. Dates are `YYYY-MM-DD` and times `HH:MM:SS` text, read as UTC. The spring timetable is mostly the fall one with ids plus 3000, but 15 spring classes have no fall twin, so all 147 classes are carried. `sqlite_sequence` is not data.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/school.md`](../../docs/research/spider2/school.md).

## How the log was made

Each enrolment is an event owned by the student, and so are its outcome, a completion with the grade or a withdrawal. Student_Schedules is rebuilt from them: `ClassStatus` is 2 when completed, 3 when withdrawn and 1 otherwise, and `Grade` is the completion's grade, else 0.0. The rule is exact on 120 of 120 rows: fall enrolments ended as 68 completions and 2 withdrawals, and the 50 spring enrolments are still open.

Buildings, rooms, departments, categories, subjects, majors, statuses, staff, faculty, classes and students are entities, and so are the three faculty links and the class-teacher link. A link's `ext_id` is its two source ids joined by `/`. `SubjectPreReq` names a `SubjectCode`, not a `SubjectID`, so it travels as text.

Four columns are state known only at the snapshot time N, and travel on `<entity>_snapshot` events at N, not on creation: `Students.StudGPA`, `Staff.Salary` and the faculty's `Title`, `Status` and `Tenured`. StudGPA is not a function of the grades: it is within 0.01 of the mean completed grade for 0 of 18 students.

`uv run dataset build school` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `buildings_created` | entity | 6 | `building_id`, `ext_id`, `building_name`, `number_of_floors`, `elevator_access`, `site_parking_available` |
| `class_rooms_created` | entity | 47 | `class_room_id`, `ext_id`, `building_id`, `phone_available` |
| `staff_created` | entity | 27 | `staff_id`, `ext_id`, `first_name`, `last_name`, `street_address`, `city`, `state`, `zip`, `area_code`, `phone`, `position` |
| `departments_created` | entity | 5 | `department_id`, `ext_id`, `dept_name`, `dept_chair` |
| `categories_created` | entity | 19 | `category_id`, `ext_id`, `description`, `department_id` |
| `subjects_created` | entity | 56 | `subject_id`, `ext_id`, `category_id`, `subject_code`, `subject_name`, `subject_prereq`, `subject_description` |
| `majors_created` | entity | 7 | `major_id`, `ext_id`, `major` |
| `student_class_status_created` | entity | 3 | `class_status_id`, `ext_id`, `description` |
| `faculty_created` | entity | 24 | `faculty_id`, `ext_id`, `staff_id` |
| `faculty_categories_created` | entity | 76 | `fc_id`, `ext_id`, `faculty_id`, `category_id` |
| `faculty_subjects_created` | entity | 110 | `fs_id`, `ext_id`, `faculty_id`, `subject_id`, `proficiency_rating` |
| `classes_created` | entity | 147 | `class_id`, `ext_id`, `subject_id`, `class_room_id`, `credits`, `duration`, `monday`, `tuesday`, `wednesday`, `thursday`, `friday`, `saturday` |
| `faculty_classes_created` | entity | 145 | `fcl_id`, `ext_id`, `class_id`, `staff_id` |
| `students_created` | entity | 19 | `student_id`, `ext_id`, `first_name`, `last_name`, `street_address`, `city`, `state`, `zip`, `area_code`, `phone`, `major_id` |
| `student_enrolled` | business | 120 | `student_id`, `class_id` |
| `class_completed` | business | 68 | `student_id`, `class_id`, `grade` |
| `class_withdrawn` | business | 2 | `student_id`, `class_id` |
| `students_snapshot` | business | 19 | `student_id`, `stud_gpa` |
| `staff_snapshot` | business | 27 | `staff_id`, `salary` |
| `faculty_snapshot` | business | 24 | `faculty_id`, `title`, `status`, `tenured` |

## Times set by rule

The source has no enrolment, completion, withdrawal or grading date, so every business event's time is a rule. A sim that fits "time to completion" here would fit the rule.
- An enrolment is at its class's start, `StartDate` + `StartTime`.
- Completions and withdrawals are at T_end = 2018-01-14 00:00, the day before the spring term.
- Snapshots are at N = 2018-01-20 09:00, the last class start.
- Lookups, the faculty category and subject links, and students are created at T0 = 2017-09-11 00:00, the first class date.

Natural times: staff and faculty are created at their hire date, and a class (with its teacher link) at its first meeting.

## Expected output

`results/` holds every source table, as the source stores it. Each column's type follows the values it holds: text, int64 or float64. A mixed column holds text and numbers together, so it is stored as SQLite's own text rendering and declared in `dataset.toml`.

| Table | Rows | Columns | Mixed columns |
|---|---:|---:|---|
| `Buildings` | 6 | 5 | none |
| `Class_Rooms` | 47 | 3 | none |
| `Departments` | 5 | 3 | none |
| `Categories` | 19 | 3 | none |
| `Subjects` | 56 | 6 | none |
| `Majors` | 7 | 2 | none |
| `Student_Class_Status` | 3 | 2 | none |
| `Staff` | 27 | 12 | none |
| `Faculty` | 24 | 4 | none |
| `Faculty_Categories` | 76 | 2 | none |
| `Faculty_Subjects` | 110 | 3 | none |
| `Classes` | 147 | 13 | none |
| `Faculty_Classes` | 145 | 2 | none |
| `Students` | 19 | 11 | none |
| `Student_Schedules` | 120 | 4 | none |

`expected/queries/` holds the answer of the saved question (`local130`), computed on the source. `dataset verify` runs `specs/build.sql` over the log, loads the tables into SQLite with the source's DDL, and compares them and the answers exactly: rows as multisets, numbers by value, text byte for byte.

local130 ranks the 18 completions of English classes (`Subjects.CategoryID = 'ENG'`) into quintiles by the share of completions with a grade at least as high: Bishop 98.07 is First, Lum 67.19 is Fifth. There is no gold SQL; the query is written from the question and reproduces the gold variant `local130_a`. It ranks on `Grade` and filters on `ClassStatus`, so it depends on the completion lifecycle rebuilding both exactly.

The REAL columns (grades, GPAs, salaries and proficiency ratings) are carried as float64 verbatim; each is a short decimal that round-trips through its shortest representation.

## Regenerate

```bash
uv run refdata fetch                 # once: the Spider 2.0 SQLite files → data/spider2/
uv run dataset build school             # → $NEORISK_DATA_ROOT/school/v1/ (default data/datasets/)
uv run dataset verify school            # exit 0 = every table and answer matches
```

## Extend

- **More rows:** not possible for a fixed source. Stage 2 will generate logs from `specs/pack.py`.
- **A new event type:** declare it in `specs/pack.py`, add its `-- event: <name> owner=<col>` block to `specs/ingest.sql`, and use it in `specs/build.sql`.
- **A new attribute:** add the column to the pack table and to its ingest block. It then appears in the payload and in `schema/events.json`.
- **A new results table:** add it to `specs/source.toml` and a `-- table: <name>` block to `specs/build.sql`.
- **A new saved question:** add `specs/queries/<id>.sql` (SQLite dialect, source table names).
- **A new engine port:** write `engines/<engine>/` from `specs/build.sql`. It must read only the log and match `results/` exactly.
- **Prerequisites as a graph:** `subject_prereq` is a `SubjectCode`; a ref would need a code-keyed lookup, which refs by `ext_id` do not provide.

Any change to `specs/`, `dataset.toml` or the source changes the build. Once a version is recorded in `v1.lock.json`, changed output needs a new version (`v2`).
