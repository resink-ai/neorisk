-- name: row_counts
SELECT 'course' t, count(*) n FROM university_course UNION ALL SELECT 'enrollment', count(*) FROM university_enrollment UNION ALL
SELECT 'faculty', count(*) FROM university_faculty UNION ALL SELECT 'offering', count(*) FROM university_offering UNION ALL SELECT 'student', count(*) FROM university_student;
-- name: typeof_columns
SELECT 'faculty.FacSupervisor' c, typeof(FacSupervisor) ty, count(*) n FROM university_faculty GROUP BY 2 UNION ALL
SELECT 'faculty.FacNo', typeof(FacNo), count(*) FROM university_faculty GROUP BY 2 UNION ALL
SELECT 'faculty.FacSalary', typeof(FacSalary), count(*) FROM university_faculty GROUP BY 2 UNION ALL
SELECT 'faculty.FacHireDate', typeof(FacHireDate), count(*) FROM university_faculty GROUP BY 2 UNION ALL
SELECT 'faculty.FacZipCode', typeof(FacZipCode), count(*) FROM university_faculty GROUP BY 2 UNION ALL
SELECT 'offering.FacNo', typeof(FacNo), count(*) FROM university_offering GROUP BY 2 UNION ALL
SELECT 'offering.OffYear', typeof(OffYear), count(*) FROM university_offering GROUP BY 2 UNION ALL
SELECT 'student.StdNo', typeof(StdNo), count(*) FROM university_student GROUP BY 2 UNION ALL
SELECT 'student.StdGPA', typeof(StdGPA), count(*) FROM university_student GROUP BY 2 UNION ALL
SELECT 'enrollment.EnrGrade', typeof(EnrGrade), count(*) FROM university_enrollment GROUP BY 2;
-- name: key_uniqueness
SELECT 'course.CourseNo' k, count(*)-count(DISTINCT CourseNo) d FROM university_course UNION ALL
SELECT 'faculty.FacNo', count(*)-count(DISTINCT FacNo) FROM university_faculty UNION ALL
SELECT 'student.StdNo', count(*)-count(DISTINCT StdNo) FROM university_student UNION ALL
SELECT 'offering.OfferNo', count(*)-count(DISTINCT OfferNo) FROM university_offering UNION ALL
SELECT 'enrollment (OfferNo,StdNo)', count(*)-(SELECT count(*) FROM (SELECT DISTINCT OfferNo, StdNo FROM university_enrollment)) FROM university_enrollment;
-- name: fk_orphans
SELECT 'enrollment.OfferNo' j, sum(o.OfferNo IS NULL) orphans, count(*) n FROM university_enrollment e LEFT JOIN university_offering o USING(OfferNo) UNION ALL
SELECT 'enrollment.StdNo', sum(s.StdNo IS NULL), count(*) FROM university_enrollment e LEFT JOIN university_student s USING(StdNo) UNION ALL
SELECT 'offering.CourseNo', sum(c.CourseNo IS NULL), count(*) FROM university_offering o LEFT JOIN university_course c USING(CourseNo) UNION ALL
SELECT 'offering.FacNo (non-null)', sum(f.FacNo IS NULL), count(*) FROM university_offering o LEFT JOIN university_faculty f ON f.FacNo = o.FacNo WHERE o.FacNo IS NOT NULL UNION ALL
SELECT 'faculty.FacSupervisor (non-null)', sum(f.FacNo IS NULL), count(*) FROM university_faculty x LEFT JOIN university_faculty f ON f.FacNo = x.FacSupervisor WHERE x.FacSupervisor IS NOT NULL;
-- name: unused_parents
SELECT 'offerings w/o enrollment' w, count(*) n, group_concat(OfferNo) ids FROM university_offering WHERE OfferNo NOT IN (SELECT OfferNo FROM university_enrollment) UNION ALL
SELECT 'courses w/o offering', count(*), group_concat(CourseNo) FROM university_course WHERE CourseNo NOT IN (SELECT CourseNo FROM university_offering) UNION ALL
SELECT 'faculty w/o offering', count(*), group_concat(FacNo) FROM university_faculty WHERE FacNo NOT IN (SELECT FacNo FROM university_offering WHERE FacNo IS NOT NULL) UNION ALL
SELECT 'students w/o enrollment', count(*), group_concat(StdNo) FROM university_student WHERE StdNo NOT IN (SELECT StdNo FROM university_enrollment);
-- name: faculty_also_student
SELECT f.FacNo, f.FacFirstName, f.FacLastName, s.StdClass FROM university_faculty f JOIN university_student s ON s.StdNo = f.FacNo;
-- name: faculty_no_leading_zero
-- Mannino's FacNo 098765432 is a 9-digit text id; here INTEGER loses the zero
SELECT FacNo, length(CAST(FacNo AS TEXT)) len FROM university_faculty WHERE length(CAST(FacNo AS TEXT)) <> 9;
-- name: gpa_vs_grades
SELECT s.StdNo, s.StdGPA, round(avg(e.EnrGrade),4) avg_grade, count(e.EnrGrade) n FROM university_student s LEFT JOIN university_enrollment e USING(StdNo) GROUP BY 1 ORDER BY 1;
-- name: gpa_equals_avg
SELECT sum(abs(s.StdGPA - a.g) < 0.05) within_005, count(*) n FROM university_student s JOIN (SELECT StdNo, avg(EnrGrade) g FROM university_enrollment GROUP BY 1) a USING(StdNo);
-- name: terms
SELECT OffYear, OffTerm, count(*) n FROM university_offering GROUP BY 1,2 ORDER BY 1,2;
-- name: enrollment_by_term
SELECT o.OffYear, o.OffTerm, count(*) n FROM university_enrollment e JOIN university_offering o USING(OfferNo) GROUP BY 1,2;
-- name: student_double_booking
-- same student, same term, same days & time (timetable clash)?
SELECT e1.StdNo, o1.OfferNo, o2.OfferNo, o1.OffTerm, o1.OffYear, o1.OffTime, o1.OffDays FROM university_enrollment e1 JOIN university_enrollment e2 ON e1.StdNo=e2.StdNo AND e1.OfferNo < e2.OfferNo JOIN university_offering o1 ON o1.OfferNo=e1.OfferNo JOIN university_offering o2 ON o2.OfferNo=e2.OfferNo WHERE o1.OffTerm=o2.OffTerm AND o1.OffYear=o2.OffYear AND o1.OffTime=o2.OffTime AND o1.OffDays=o2.OffDays;
-- name: grade_decimals
SELECT sum(round(EnrGrade,1) = EnrGrade) dp1, count(*) n, min(EnrGrade), max(EnrGrade) FROM university_enrollment UNION ALL SELECT sum(round(StdGPA,1)=StdGPA), count(*), min(StdGPA), max(StdGPA) FROM university_student;
-- name: rank_salary
SELECT FacRank, count(*) n, avg(FacSalary) av, min(FacSalary), max(FacSalary) FROM university_faculty GROUP BY 1;
-- name: hire_vs_offering
SELECT min(FacHireDate), max(FacHireDate), (SELECT min(OffYear) FROM university_offering) first_off_year FROM university_faculty;
-- name: whitespace_case
SELECT sum(FacFirstName <> upper(FacFirstName)) lower_fac, (SELECT sum(StdFirstName <> upper(StdFirstName)) FROM university_student) lower_std, (SELECT count(*) FROM university_offering WHERE OffTime <> trim(OffTime)) ws FROM university_faculty;
-- name: rowid_order
SELECT 'offering' t, sum(nxt < cur) d FROM (SELECT OfferNo cur, lead(OfferNo) OVER (ORDER BY rowid) nxt FROM university_offering) UNION ALL
SELECT 'faculty', sum(nxt < cur) FROM (SELECT FacNo cur, lead(FacNo) OVER (ORDER BY rowid) nxt FROM university_faculty) UNION ALL
SELECT 'student', sum(nxt < cur) FROM (SELECT StdNo cur, lead(StdNo) OVER (ORDER BY rowid) nxt FROM university_student) UNION ALL
SELECT 'enrollment', sum(nxt < cur) FROM (SELECT printf('%06d%012d',OfferNo,StdNo) cur, lead(printf('%06d%012d',OfferNo,StdNo)) OVER (ORDER BY rowid) nxt FROM university_enrollment);
-- name: gold_local163
WITH a AS (SELECT FacRank, avg(FacSalary) av FROM university_faculty GROUP BY 1),
d AS (SELECT f.FacRank, f.FacFirstName, f.FacLastName, f.FacSalary, abs(f.FacSalary - a.av) diff FROM university_faculty f JOIN a USING(FacRank))
SELECT d.FacRank, d.FacFirstName, d.FacLastName, d.FacSalary FROM d JOIN (SELECT FacRank, min(diff) m FROM d GROUP BY 1) m ON m.FacRank=d.FacRank AND d.diff=m.m ORDER BY 1,2;
-- name: enrollments_per_offering
SELECT o.OfferNo, count(e.StdNo) n FROM university_offering o LEFT JOIN university_enrollment e USING(OfferNo) GROUP BY 1 ORDER BY 2, 1;
-- name: grade_mean
SELECT round(avg(EnrGrade),4) mean_grade, count(*) n, round(count(*)*1.0/(SELECT count(*) FROM university_student),2) per_student FROM university_enrollment;
