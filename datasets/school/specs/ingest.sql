-- school: source tables → events (refdata ingest). Rule times: lookups, links and students
-- at T0 = 2017-09-11 00:00 (the first class date); enrolment at the class's start;
-- completion and withdrawal at T_end = 2018-01-14 00:00 (the day before the spring term);
-- snapshots at N = 2018-01-20 09:00, the last class start.

-- entity: buildings
SELECT BuildingCode AS ext_id, '2017-09-11 00:00:00' AS created_at,
       BuildingName AS building_name, NumberOfFloors AS number_of_floors,
       ElevatorAccess AS elevator_access, SiteParkingAvailable AS site_parking_available
FROM Buildings ORDER BY BuildingCode;

-- entity: class_rooms
SELECT CAST(ClassRoomID AS TEXT) AS ext_id, '2017-09-11 00:00:00' AS created_at,
       BuildingCode AS building_id, PhoneAvailable AS phone_available
FROM Class_Rooms ORDER BY ClassRoomID;

-- entity: staff
SELECT CAST(StaffID AS TEXT) AS ext_id, DateHired || ' 00:00:00' AS created_at,
       StfFirstName AS first_name, StfLastname AS last_name, StfStreetAddress AS street_address,
       StfCity AS city, StfState AS state, StfZipCode AS zip, StfAreaCode AS area_code,
       StfPhoneNumber AS phone, Position AS position
FROM Staff ORDER BY StaffID;

-- entity: departments
SELECT CAST(DepartmentID AS TEXT) AS ext_id, '2017-09-11 00:00:00' AS created_at,
       DeptName AS dept_name, CAST(DeptChair AS TEXT) AS dept_chair
FROM Departments ORDER BY DepartmentID;

-- entity: categories
SELECT CategoryID AS ext_id, '2017-09-11 00:00:00' AS created_at,
       CategoryDescription AS description, CAST(DepartmentID AS TEXT) AS department_id
FROM Categories ORDER BY CategoryID;

-- entity: subjects
SELECT CAST(SubjectID AS TEXT) AS ext_id, '2017-09-11 00:00:00' AS created_at,
       CategoryID AS category_id, SubjectCode AS subject_code, SubjectName AS subject_name,
       SubjectPreReq AS subject_prereq, SubjectDescription AS subject_description
FROM Subjects ORDER BY SubjectID;

-- entity: majors
SELECT CAST(MajorID AS TEXT) AS ext_id, '2017-09-11 00:00:00' AS created_at, Major AS major
FROM Majors ORDER BY MajorID;

-- entity: student_class_status
SELECT CAST(ClassStatus AS TEXT) AS ext_id, '2017-09-11 00:00:00' AS created_at,
       ClassStatusDescription AS description
FROM Student_Class_Status ORDER BY ClassStatus;

-- entity: faculty
SELECT CAST(f.StaffID AS TEXT) AS ext_id, s.DateHired || ' 00:00:00' AS created_at,
       CAST(f.StaffID AS TEXT) AS staff_id
FROM Faculty f JOIN Staff s USING (StaffID) ORDER BY f.StaffID;

-- entity: faculty_categories
SELECT StaffID || '/' || CategoryID AS ext_id, '2017-09-11 00:00:00' AS created_at,
       CAST(StaffID AS TEXT) AS faculty_id, CategoryID AS category_id
FROM Faculty_Categories ORDER BY StaffID, CategoryID;

-- entity: faculty_subjects
SELECT StaffID || '/' || SubjectID AS ext_id, '2017-09-11 00:00:00' AS created_at,
       CAST(StaffID AS TEXT) AS faculty_id, CAST(SubjectID AS TEXT) AS subject_id,
       ProficiencyRating AS proficiency_rating
FROM Faculty_Subjects ORDER BY StaffID, SubjectID;

-- entity: classes
SELECT CAST(ClassID AS TEXT) AS ext_id, StartDate || ' ' || StartTime AS created_at,
       CAST(SubjectID AS TEXT) AS subject_id, CAST(ClassRoomID AS TEXT) AS class_room_id,
       Credits AS credits, Duration AS duration, MondaySchedule AS monday,
       TuesdaySchedule AS tuesday, WednesdaySchedule AS wednesday, ThursdaySchedule AS thursday,
       FridaySchedule AS friday, SaturdaySchedule AS saturday
FROM Classes ORDER BY ClassID;

-- entity: faculty_classes
SELECT x.ClassID || '/' || x.StaffID AS ext_id, c.StartDate || ' ' || c.StartTime AS created_at,
       CAST(x.ClassID AS TEXT) AS class_id, CAST(x.StaffID AS TEXT) AS staff_id
FROM Faculty_Classes x JOIN Classes c USING (ClassID) ORDER BY x.ClassID, x.StaffID;

-- entity: students
SELECT CAST(StudentID AS TEXT) AS ext_id, '2017-09-11 00:00:00' AS created_at,
       StudFirstName AS first_name, StudLastName AS last_name,
       StudStreetAddress AS street_address, StudCity AS city, StudState AS state,
       StudZipCode AS zip, StudAreaCode AS area_code, StudPhoneNumber AS phone,
       CAST(StudMajor AS TEXT) AS major_id
FROM Students ORDER BY StudentID;

-- event: student_enrolled owner=student_id ord=class
SELECT c.StartDate || ' ' || c.StartTime AS event_time, s.ClassID AS class,
       CAST(s.StudentID AS TEXT) AS student_id, CAST(s.ClassID AS TEXT) AS class_id
FROM Student_Schedules s JOIN Classes c USING (ClassID) ORDER BY s.StudentID, s.ClassID;

-- event: class_completed owner=student_id ord=class
SELECT '2018-01-14 00:00:00' AS event_time, ClassID AS class,
       CAST(StudentID AS TEXT) AS student_id, CAST(ClassID AS TEXT) AS class_id, Grade AS grade
FROM Student_Schedules WHERE ClassStatus = 2 ORDER BY StudentID, ClassID;

-- event: class_withdrawn owner=student_id ord=class
SELECT '2018-01-14 00:00:00' AS event_time, ClassID AS class,
       CAST(StudentID AS TEXT) AS student_id, CAST(ClassID AS TEXT) AS class_id
FROM Student_Schedules WHERE ClassStatus = 3 ORDER BY StudentID, ClassID;

-- event: students_snapshot owner=student_id
SELECT '2018-01-20 09:00:00' AS event_time, CAST(StudentID AS TEXT) AS student_id,
       StudGPA AS stud_gpa
FROM Students ORDER BY StudentID;

-- event: staff_snapshot owner=staff_id
SELECT '2018-01-20 09:00:00' AS event_time, CAST(StaffID AS TEXT) AS staff_id, Salary AS salary
FROM Staff ORDER BY StaffID;

-- event: faculty_snapshot owner=faculty_id
SELECT '2018-01-20 09:00:00' AS event_time, CAST(StaffID AS TEXT) AS faculty_id, Title AS title,
       Status AS status, Tenured AS tenured
FROM Faculty ORDER BY StaffID;
