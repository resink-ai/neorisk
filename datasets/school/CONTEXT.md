# school

## What this is

A school's timetable over two terms: students enrol in class sections, then complete them with a grade or withdraw; staff teach classes in rooms, by subject and category.

Version `v1`, kind `spider2`. The input is one ordered event log of 1,119 events; the output is the 15 source tables, rebuilt exactly, and the answer to 1 saved Spider 2.0 question.

## Raw data

`school_scheduling.sqlite`, 15 tables. The School Scheduling sample database from John L. Viescas and Michael J. Hernandez, *SQL Queries for Mere Mortals*: hand-made course data. The licence is unstated; the files ship with the book for its readers.

Classes start in fall 2017 (2017-09-11, 12 and 16) and spring 2018 (2018-01-15, 16 and 20); staff were hired 1982–1992. Dates are `YYYY-MM-DD` and times `HH:MM:SS` text, read as UTC. The spring timetable is mostly the fall one with ids plus 3000, but 15 spring classes have no fall twin, so all 147 classes are carried. `sqlite_sequence` is not data.

The reverse-engineering research, with the queries behind every number, is in [`docs/research/spider2/school.md`](../../docs/research/spider2/school.md).

## How the log was made

Each enrolment is an event owned by the student, and so are its outcome, a completion with the grade or a withdrawal. Student_Schedules is rebuilt from them: `ClassStatus` is 2 when completed, 3 when withdrawn and 1 otherwise, and `Grade` is the completion's grade, else 0.0. The rule is exact on 120 of 120 rows: fall enrolments ended as 68 completions and 2 withdrawals, and the 50 spring enrolments are still open.

Buildings, rooms, departments, categories, subjects, majors, statuses, staff, faculty, classes and students are entities, and so are the three faculty links and the class-teacher link. A link's `ext_id` is its two source ids joined by `/`. `SubjectPreReq` names a `SubjectCode`, not a `SubjectID`, so it travels as text.

Addresses, phones, positions, salaries, the department chair, the faculty's `Title`, `Status` and `Tenured`, a student's major and `StudGPA`, the building and room amenity flags and each faculty proficiency rating are state known only at the snapshot time N, so they travel on `<entity>_snapshot` events at N, not on creation. StudGPA is not a function of the grades: it is within 0.01 of the mean completed grade for 0 of 18 students. Staff and faculty are created by `staff_hired` and `faculty_hired`, at the hire date.

`uv run dataset build school` runs `specs/ingest.sql` on the read-only source to make a simkit dataset (an internal stage), then writes it as one log. Entity rows become `<entity>_created` events at their creation time; business events keep their columns. The log is in `seq` order: event time, then entities before events at the same instant. Each row's `payload` is a JSON object whose fields are listed in `schema/events.json`.

## Event catalogue

| Event | Kind | Rows | Payload fields |
|---|---|---:|---|
| `buildings_created` | entity | 6 | `building_id`, `ext_id`, `building_name`, `number_of_floors` |
| `class_rooms_created` | entity | 47 | `class_room_id`, `ext_id`, `building_id` |
| `staff_hired` | entity | 27 | `staff_id`, `ext_id`, `first_name`, `last_name` |
| `departments_created` | entity | 5 | `department_id`, `ext_id`, `dept_name` |
| `categories_created` | entity | 19 | `category_id`, `ext_id`, `description`, `department_id` |
| `subjects_created` | entity | 56 | `subject_id`, `ext_id`, `category_id`, `subject_code`, `subject_name`, `subject_prereq`, `subject_description` |
| `majors_created` | entity | 7 | `major_id`, `ext_id`, `major` |
| `student_class_status_created` | entity | 3 | `class_status_id`, `ext_id`, `description` |
| `faculty_hired` | entity | 24 | `faculty_id`, `ext_id`, `staff_id` |
| `faculty_categories_created` | entity | 76 | `fc_id`, `ext_id`, `faculty_id`, `category_id` |
| `faculty_subjects_created` | entity | 110 | `fs_id`, `ext_id`, `faculty_id`, `subject_id` |
| `classes_created` | entity | 147 | `class_id`, `ext_id`, `subject_id`, `class_room_id`, `credits`, `duration`, `monday`, `tuesday`, `wednesday`, `thursday`, `friday`, `saturday` |
| `faculty_classes_created` | entity | 145 | `fcl_id`, `ext_id`, `class_id`, `staff_id` |
| `students_created` | entity | 19 | `student_id`, `ext_id`, `first_name`, `last_name` |
| `student_enrolled` | business | 120 | `student_id`, `class_id` |
| `class_completed` | business | 68 | `student_id`, `class_id`, `grade` |
| `class_withdrawn` | business | 2 | `student_id`, `class_id` |
| `buildings_snapshot` | business | 6 | `building_id`, `elevator_access`, `site_parking_available` |
| `class_rooms_snapshot` | business | 47 | `class_room_id`, `phone_available` |
| `departments_snapshot` | business | 5 | `department_id`, `dept_chair` |
| `faculty_subjects_snapshot` | business | 110 | `fs_id`, `proficiency_rating` |
| `students_snapshot` | business | 19 | `student_id`, `street_address`, `city`, `state`, `zip`, `area_code`, `phone`, `major_id`, `stud_gpa` |
| `staff_snapshot` | business | 27 | `staff_id`, `street_address`, `city`, `state`, `zip`, `area_code`, `phone`, `position`, `salary` |
| `faculty_snapshot` | business | 24 | `faculty_id`, `title`, `status`, `tenured` |

## Times set by rule

The source has no enrolment, completion, withdrawal or grading date, so every business event's time is a rule. A sim that fits "time to completion" here would fit the rule.
- An enrolment is at its class's start, `StartDate` + `StartTime`.
- Completions and withdrawals are at T_end = 2018-01-14 00:00, the day before the spring term.
- Snapshots are at N = 2018-01-20 09:00, the last class start and so the latest event time in the log.
- Lookups, the faculty category and subject links, and students are created at T0 = 2017-09-11 00:00, the first class date.

Natural times: staff and faculty are created at their hire date, and a class (with its teacher link) at its first meeting.

## Snapshot columns

| Entity | Snapshot event | At (UTC) | Rows | Columns |
|---|---|---|---:|---|
| `buildings` | `buildings_snapshot` | 2018-01-20 09:00:00 | 6 | `elevator_access`, `site_parking_available` |
| `class_rooms` | `class_rooms_snapshot` | 2018-01-20 09:00:00 | 47 | `phone_available` |
| `departments` | `departments_snapshot` | 2018-01-20 09:00:00 | 5 | `dept_chair` |
| `faculty_subjects` | `faculty_subjects_snapshot` | 2018-01-20 09:00:00 | 110 | `proficiency_rating` |
| `students` | `students_snapshot` | 2018-01-20 09:00:00 | 19 | `street_address`, `city`, `state`, `zip`, `area_code`, `phone`, `major_id`, `stud_gpa` |
| `staff` | `staff_snapshot` | 2018-01-20 09:00:00 | 27 | `street_address`, `city`, `state`, `zip`, `area_code`, `phone`, `position`, `salary` |
| `faculty` | `faculty_snapshot` | 2018-01-20 09:00:00 | 24 | `title`, `status`, `tenured` |

| Column | Verdict | Reason |
|---|---|---|
| `buildings.ext_id` | creation | The source key (`BuildingCode`). |
| `buildings.building_name` | creation | A given name. |
| `buildings.number_of_floors` | creation | Fixed when the building was built; the source shows no change. |
| `buildings.elevator_access` | snapshot | An amenity flag that can change after creation (an elevator can be added); when in doubt, snapshot. Research kept it on creation. |
| `buildings.site_parking_available` | snapshot | An amenity flag that can change; when in doubt, snapshot. Research kept it on creation. |
| `class_rooms.ext_id` | creation | The source key (`ClassRoomID`). |
| `class_rooms.building_id` | creation | An immutable ref: the building the room is in. |
| `class_rooms.phone_available` | snapshot | An amenity flag that can change; when in doubt, snapshot. Research kept it on creation. |
| `staff.ext_id` | creation | The source key (`StaffID`). |
| `staff.first_name` | creation | Given names. |
| `staff.last_name` | creation | Given names. |
| `staff.created_at` (`DateHired`) | creation | The hire date; it is the event's time. |
| `staff.street_address` | snapshot | An address, known only as of the extract. Research kept it on creation. |
| `staff.city` | snapshot | An address. Research kept it on creation. |
| `staff.state` | snapshot | An address. Research kept it on creation. |
| `staff.zip` | snapshot | An address. Research kept it on creation. |
| `staff.area_code` | snapshot | A phone. Research kept it on creation. |
| `staff.phone` | snapshot | A phone. Research kept it on creation. |
| `staff.position` | snapshot | A title held, which can change after the hire. Research kept it on creation. |
| `staff.salary` | snapshot | A salary; the source has only the value at N. |
| `departments.ext_id` | creation | The source key (`DepartmentID`). |
| `departments.dept_name` | creation | A given name. |
| `departments.dept_chair` | snapshot | The chair is a title held and rotates; the source has only the current one. Research kept it on creation. |
| `categories.ext_id` | creation | The source key (`CategoryID`). |
| `categories.description` | creation | The category's title. |
| `categories.department_id` | creation | The department the category was created in; the source shows no change. |
| `subjects.ext_id` | creation | The source key (`SubjectID`). |
| `subjects.category_id` | creation | The category the subject was created in. |
| `subjects.subject_code` | creation | A given code. |
| `subjects.subject_name` | creation | A title. |
| `subjects.subject_prereq` | creation | Part of the subject's catalog definition; the source shows no change. |
| `subjects.subject_description` | creation | Part of the subject's catalog definition. |
| `majors.ext_id` | creation | The source key (`MajorID`). |
| `majors.major` | creation | A given name. |
| `student_class_status.ext_id` | creation | The source key (`ClassStatus`). |
| `student_class_status.description` | creation | A given name. |
| `faculty.ext_id` | creation | The source key (`StaffID`). |
| `faculty.staff_id` | creation | An immutable ref: the staff member the faculty row is. |
| `faculty.title` | snapshot | A title held; current state. |
| `faculty.status` | snapshot | Current state (including "On Leave"). |
| `faculty.tenured` | snapshot | Current state; tenure is granted after the hire. |
| `faculty_categories.ext_id` | creation | The link's two source ids; a link has no other attribute. |
| `faculty_categories.faculty_id` | creation | An immutable ref: one end of the link. |
| `faculty_categories.category_id` | creation | An immutable ref: one end of the link. |
| `faculty_subjects.ext_id` | creation | The link's two source ids. |
| `faculty_subjects.faculty_id` | creation | An immutable ref: one end of the link. |
| `faculty_subjects.subject_id` | creation | An immutable ref: one end of the link. |
| `faculty_subjects.proficiency_rating` | snapshot | A rating, which the rubric lists as snapshot. Research called the links static. |
| `classes.ext_id` | creation | The source key (`ClassID`). |
| `classes.subject_id` | creation | An immutable ref: the subject the section is of. |
| `classes.class_room_id` | creation | The published timetable that defines the section. |
| `classes.credits` | creation | The published timetable that defines the section. |
| `classes.created_at` (`StartDate`, `StartTime`) | creation | The first meeting; it is the event's time. |
| `classes.duration` | creation | The published timetable that defines the section. |
| `classes.monday … saturday` | creation | The published timetable that defines the section (six day flags). |
| `faculty_classes.ext_id` | creation | The link's two source ids. |
| `faculty_classes.class_id` | creation | An immutable ref: one end of the link. |
| `faculty_classes.staff_id` | creation | An immutable ref: the teacher the link was created with. |
| `students.ext_id` | creation | The source key (`StudentID`). |
| `students.first_name` | creation | Given names. |
| `students.last_name` | creation | Given names. |
| `students.street_address` | snapshot | An address. Research kept it on creation. |
| `students.city` | snapshot | An address. Research kept it on creation. |
| `students.state` | snapshot | An address. Research kept it on creation. |
| `students.zip` | snapshot | An address. Research kept it on creation. |
| `students.area_code` | snapshot | A phone. Research kept it on creation. |
| `students.phone` | snapshot | A phone. Research kept it on creation. |
| `students.major_id` | snapshot | A student can change major; when in doubt, snapshot. Research kept it on creation. |
| `students.stud_gpa` | snapshot | A stored GPA the grades do not explain (0 of 18 match). |

Only staff and faculty carry a domain name: their creation is a hire the source dates. Students, classes and lookups are created by rule, so they keep `<entity>_created`.

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
