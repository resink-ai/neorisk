-- University: events → source tables (refdata rebuild, DuckDB). Faculty refs are written back
-- as doubles (the source stores them REAL); grades and GPAs come back from tenths.

-- table: university_course
SELECT ext_id AS CourseNo, crs_desc AS CrsDesc, crs_units AS CrsUnits FROM course;

-- table: university_faculty
SELECT CAST(f.ext_id AS BIGINT) AS FacNo, f.first_name AS FacFirstName,
       f.last_name AS FacLastName, f.city AS FacCity, f.state AS FacState, f.dept AS FacDept,
       s.rank AS FacRank, s.salary AS FacSalary, CAST(b.ext_id AS DOUBLE) AS FacSupervisor,
       strftime(f.created_at AT TIME ZONE 'UTC', '%Y-%m-%d') AS FacHireDate, f.zip AS FacZipCode
FROM faculty f JOIN faculty_snapshot s USING (faculty_id)
LEFT JOIN faculty b ON b.faculty_id = f.supervisor_id;

-- table: university_student
SELECT CAST(t.ext_id AS BIGINT) AS StdNo, t.first_name AS StdFirstName,
       t.last_name AS StdLastName, t.city AS StdCity, t.state AS StdState, t.zip AS StdZip,
       t.major AS StdMajor, s.class AS StdClass, CAST(s.gpa_tenths AS DOUBLE) / 10 AS StdGPA
FROM student t JOIN student_snapshot s USING (student_id);

-- table: university_offering
SELECT CAST(o.ext_id AS BIGINT) AS OfferNo, c.ext_id AS CourseNo, o.term AS OffTerm,
       o.year AS OffYear, o.location AS OffLocation, o.time AS OffTime,
       CAST(f.ext_id AS DOUBLE) AS FacNo, o.days AS OffDays
FROM offering o JOIN course c USING (course_id)
LEFT JOIN faculty f ON f.faculty_id = o.faculty_id;

-- table: university_enrollment
-- Every enrollment has its grade: the 37 grade_recorded pairs are the 37 student_enrolled ones.
SELECT CAST(o.ext_id AS BIGINT) AS OfferNo, CAST(t.ext_id AS BIGINT) AS StdNo,
       CAST(g.grade_tenths AS DOUBLE) / 10 AS EnrGrade
FROM student_enrolled e
JOIN grade_recorded g USING (student_id, offering_id)
JOIN offering o USING (offering_id) JOIN student t USING (student_id);
