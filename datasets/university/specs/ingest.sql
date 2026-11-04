-- University: source tables → events (refdata ingest). Term rule (a quarter calendar):
-- WINTER y-01-01..y-03-31, SPRING y-04-01..y-06-30, SUMMER y-07-01..y-08-31, FALL y-09-01..y-12-31.
-- The REAL faculty refs (FacNo in offerings, FacSupervisor) are integral and map as integers.

-- entity: course
SELECT CourseNo AS ext_id, CrsDesc AS crs_desc, CrsUnits AS crs_units,
       '2009-07-01 00:00:00' AS created_at
FROM university_course ORDER BY CourseNo;

-- entity: faculty
SELECT CAST(FacNo AS TEXT) AS ext_id, FacFirstName AS first_name, FacLastName AS last_name,
       FacCity AS city, FacState AS state, FacDept AS dept, CAST(FacSupervisor AS INTEGER) AS supervisor_id,
       FacZipCode AS zip, FacHireDate || ' 00:00:00' AS created_at
FROM university_faculty ORDER BY FacNo;

-- entity: student
SELECT CAST(StdNo AS TEXT) AS ext_id, StdFirstName AS first_name, StdLastName AS last_name,
       StdCity AS city, StdState AS state, StdZip AS zip, StdMajor AS major,
       '2009-07-01 00:00:00' AS created_at
FROM university_student ORDER BY StdNo;

-- entity: offering
SELECT CAST(OfferNo AS TEXT) AS ext_id, CourseNo AS course_id, OffTerm AS term, OffYear AS year,
       OffLocation AS location, OffTime AS time, CAST(FacNo AS INTEGER) AS faculty_id,
       OffDays AS days,
       OffYear || CASE OffTerm WHEN 'WINTER' THEN '-01-01' WHEN 'SPRING' THEN '-04-01'
                               WHEN 'SUMMER' THEN '-07-01' WHEN 'FALL' THEN '-09-01' END
           || ' 00:00:00' AS created_at
FROM university_offering ORDER BY OfferNo;

-- event: student_enrolled owner=student_id ord=k
SELECT o.OffYear || CASE o.OffTerm WHEN 'WINTER' THEN '-01-01' WHEN 'SPRING' THEN '-04-01'
                                   WHEN 'SUMMER' THEN '-07-01' WHEN 'FALL' THEN '-09-01' END
           || ' 00:00:00' AS event_time,
       e.StdNo AS student_id, e.OfferNo AS offering_id, e.OfferNo AS k
FROM university_enrollment e JOIN university_offering o USING (OfferNo)
ORDER BY e.OfferNo, e.StdNo;

-- event: grade_recorded owner=student_id ord=k
SELECT o.OffYear || CASE o.OffTerm WHEN 'WINTER' THEN '-03-31' WHEN 'SPRING' THEN '-06-30'
                                   WHEN 'SUMMER' THEN '-08-31' WHEN 'FALL' THEN '-12-31' END
           || ' 00:00:00' AS event_time,
       e.StdNo AS student_id, e.OfferNo AS offering_id,
       CAST(round(e.EnrGrade * 10) AS INTEGER) AS grade_tenths, e.OfferNo AS k
FROM university_enrollment e JOIN university_offering o USING (OfferNo)
ORDER BY e.OfferNo, e.StdNo;

-- event: faculty_snapshot owner=faculty_id
-- At N = 2010-08-31, the rule end of Summer 2010, the last term with an offering.
SELECT '2010-08-31 00:00:00' AS event_time, FacNo AS faculty_id, FacRank AS rank,
       FacSalary AS salary
FROM university_faculty ORDER BY FacNo;

-- event: student_snapshot owner=student_id
SELECT '2010-08-31 00:00:00' AS event_time, StdNo AS student_id, StdClass AS class,
       CAST(round(StdGPA * 10) AS INTEGER) AS gpa_tenths
FROM university_student ORDER BY StdNo;
