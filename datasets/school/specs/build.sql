-- school: events → source tables (refdata rebuild, DuckDB).

-- table: Buildings
SELECT b.ext_id AS BuildingCode, b.building_name AS BuildingName,
       b.number_of_floors AS NumberOfFloors, n.elevator_access AS ElevatorAccess,
       n.site_parking_available AS SiteParkingAvailable
FROM buildings b LEFT JOIN buildings_snapshot n USING (building_id);

-- table: Class_Rooms
SELECT CAST(r.ext_id AS BIGINT) AS ClassRoomID, b.ext_id AS BuildingCode,
       n.phone_available AS PhoneAvailable
FROM class_rooms r LEFT JOIN buildings b USING (building_id)
LEFT JOIN class_rooms_snapshot n USING (class_room_id);

-- table: Departments
SELECT CAST(d.ext_id AS BIGINT) AS DepartmentID, d.dept_name AS DeptName,
       CAST(s.ext_id AS BIGINT) AS DeptChair
FROM departments d LEFT JOIN departments_snapshot n USING (department_id)
LEFT JOIN staff s ON s.staff_id = n.dept_chair;

-- table: Categories
SELECT c.ext_id AS CategoryID, c.description AS CategoryDescription,
       CAST(d.ext_id AS BIGINT) AS DepartmentID
FROM categories c LEFT JOIN departments d USING (department_id);

-- table: Subjects
SELECT CAST(s.ext_id AS BIGINT) AS SubjectID, c.ext_id AS CategoryID,
       s.subject_code AS SubjectCode, s.subject_name AS SubjectName,
       s.subject_prereq AS SubjectPreReq, s.subject_description AS SubjectDescription
FROM subjects s LEFT JOIN categories c USING (category_id);

-- table: Majors
SELECT CAST(ext_id AS BIGINT) AS MajorID, major AS Major FROM majors;

-- table: Student_Class_Status
SELECT CAST(ext_id AS BIGINT) AS ClassStatus, description AS ClassStatusDescription
FROM student_class_status;

-- table: Staff
-- Address, phone, salary and position are the snapshot at N.
SELECT CAST(s.ext_id AS BIGINT) AS StaffID, s.first_name AS StfFirstName,
       s.last_name AS StfLastname, n.street_address AS StfStreetAddress, n.city AS StfCity,
       n.state AS StfState, n.zip AS StfZipCode, n.area_code AS StfAreaCode,
       n.phone AS StfPhoneNumber, n.salary AS Salary,
       strftime(s.created_at AT TIME ZONE 'UTC', '%Y-%m-%d') AS DateHired, n.position AS Position
FROM staff s LEFT JOIN staff_snapshot n USING (staff_id);

-- table: Faculty
-- Title, Status and Tenured are the snapshot at N.
SELECT CAST(s.ext_id AS BIGINT) AS StaffID, n.title AS Title, n.status AS Status,
       n.tenured AS Tenured
FROM faculty f JOIN staff s USING (staff_id) LEFT JOIN faculty_snapshot n USING (faculty_id);

-- table: Faculty_Categories
SELECT CAST(f.ext_id AS BIGINT) AS StaffID, c.ext_id AS CategoryID
FROM faculty_categories x JOIN faculty f USING (faculty_id) JOIN categories c USING (category_id);

-- table: Faculty_Subjects
SELECT CAST(f.ext_id AS BIGINT) AS StaffID, CAST(s.ext_id AS BIGINT) AS SubjectID,
       n.proficiency_rating AS ProficiencyRating
FROM faculty_subjects x JOIN faculty f USING (faculty_id) JOIN subjects s USING (subject_id)
LEFT JOIN faculty_subjects_snapshot n USING (fs_id);

-- table: Classes
SELECT CAST(c.ext_id AS BIGINT) AS ClassID, CAST(s.ext_id AS BIGINT) AS SubjectID,
       CAST(r.ext_id AS BIGINT) AS ClassRoomID, c.credits AS Credits,
       strftime(c.created_at AT TIME ZONE 'UTC', '%Y-%m-%d') AS StartDate,
       strftime(c.created_at AT TIME ZONE 'UTC', '%H:%M:%S') AS StartTime,
       c.duration AS Duration, c.monday AS MondaySchedule, c.tuesday AS TuesdaySchedule,
       c.wednesday AS WednesdaySchedule, c.thursday AS ThursdaySchedule,
       c.friday AS FridaySchedule, c.saturday AS SaturdaySchedule
FROM classes c LEFT JOIN subjects s USING (subject_id) LEFT JOIN class_rooms r USING (class_room_id);

-- table: Faculty_Classes
SELECT CAST(c.ext_id AS BIGINT) AS ClassID, CAST(s.ext_id AS BIGINT) AS StaffID
FROM faculty_classes x JOIN classes c USING (class_id) JOIN staff s USING (staff_id);

-- table: Students
-- Address, phone, major and StudGPA are the snapshot at N.
SELECT CAST(s.ext_id AS BIGINT) AS StudentID, s.first_name AS StudFirstName,
       s.last_name AS StudLastName, n.street_address AS StudStreetAddress, n.city AS StudCity,
       n.state AS StudState, n.zip AS StudZipCode, n.area_code AS StudAreaCode,
       n.phone AS StudPhoneNumber, n.stud_gpa AS StudGPA, CAST(m.ext_id AS BIGINT) AS StudMajor
FROM students s LEFT JOIN students_snapshot n USING (student_id)
LEFT JOIN majors m ON m.major_id = n.major_id;

-- table: Student_Schedules
-- ClassStatus: 2 when completed, 3 when withdrawn, else 1 (still enrolled at N).
-- Grade: the completion's grade, else 0.0.
SELECT CAST(s.ext_id AS BIGINT) AS StudentID, CAST(c.ext_id AS BIGINT) AS ClassID,
       CASE WHEN d.student_id IS NOT NULL THEN 2 WHEN w.student_id IS NOT NULL THEN 3
            ELSE 1 END AS ClassStatus,
       coalesce(d.grade, 0.0) AS Grade
FROM student_enrolled e JOIN students s USING (student_id) JOIN classes c USING (class_id)
LEFT JOIN class_completed d ON d.student_id = e.student_id AND d.class_id = e.class_id
LEFT JOIN class_withdrawn w ON w.student_id = e.student_id AND w.class_id = e.class_id;
