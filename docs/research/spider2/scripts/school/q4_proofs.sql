-- name: status_grade_rule
-- Grade is 0 unless completed; status from lifecycle: completed (2) iff grade > 0
SELECT count(*) rows_, sum((ClassStatus=2) = (Grade>0)) completed_iff_grade_pos, sum(ClassStatus<>2 AND Grade=0) non_completed_zero FROM Student_Schedules;
-- name: status_vs_term
-- Fall-2017 classes: completed or withdrew; Spring-2018 classes: enrolled
SELECT CASE WHEN c.StartDate < '2018-01-01' THEN 'fall' ELSE 'spring' END term, s.ClassStatus, count(*) FROM Student_Schedules s JOIN Classes c USING (ClassID) GROUP BY 1,2;
-- name: faculty_is_staff_subset
SELECT count(*) faculty, sum(s.Position='Faculty') pos_faculty FROM Faculty f JOIN Staff s USING (StaffID);
-- name: staff_positions
SELECT Position, count(*), sum(StaffID IN (SELECT StaffID FROM Faculty)) in_faculty FROM Staff GROUP BY 1;
-- name: faculty_attrs
SELECT Title, Status, Tenured, count(*) FROM Faculty GROUP BY 1,2,3;
-- name: classes_without_faculty
SELECT c.ClassID, c.SubjectID, c.StartDate FROM Classes c WHERE ClassID NOT IN (SELECT ClassID FROM Faculty_Classes);
-- name: teacher_lacking_subject
SELECT f.ClassID, f.StaffID, c.SubjectID FROM Faculty_Classes f JOIN Classes c USING (ClassID) WHERE NOT EXISTS (SELECT 1 FROM Faculty_Subjects s WHERE s.StaffID=f.StaffID AND s.SubjectID=c.SubjectID);
-- name: gpa_not_derived
-- best of several candidate formulas, rows matching to 0.01
SELECT sum(abs(st.StudGPA - x.a) < 0.01) avg_completed_match, count(*) FROM Students st JOIN (SELECT StudentID, avg(CASE WHEN ClassStatus=2 THEN Grade END) a FROM Student_Schedules GROUP BY 1) x USING (StudentID);
-- name: grades_dist
SELECT (CAST(Grade AS INT)/5)*5 band, count(*) FROM Student_Schedules WHERE ClassStatus=2 GROUP BY 1;
-- name: grade_moments
SELECT avg(Grade), min(Grade), max(Grade) FROM Student_Schedules WHERE ClassStatus=2;
-- name: class_size
SELECT n, count(*) FROM (SELECT ClassID, count(*) n FROM Student_Schedules GROUP BY 1) GROUP BY 1;
-- name: subject_code_mismatch
SELECT SubjectID, CategoryID, SubjectCode FROM Subjects WHERE substr(SubjectCode,1,instr(SubjectCode,' ')-1) <> CategoryID;
-- name: student_major_null
SELECT StudentID, StudFirstName, StudLastName, StudGPA, StudMajor FROM Students WHERE StudMajor IS NULL OR StudentID=1019;
-- name: start_times
SELECT StartTime, count(*) FROM Classes GROUP BY 1;
-- name: room_conflict_pairs
SELECT a.ClassID, b.ClassID, a.ClassRoomID, a.StartDate, a.StartTime, a.Duration, b.StartTime, b.Duration FROM Classes a JOIN Classes b ON a.ClassRoomID=b.ClassRoomID AND a.ClassID<b.ClassID AND a.StartDate=b.StartDate
 AND ((a.MondaySchedule AND b.MondaySchedule) OR (a.TuesdaySchedule AND b.TuesdaySchedule) OR (a.WednesdaySchedule AND b.WednesdaySchedule) OR (a.ThursdaySchedule AND b.ThursdaySchedule) OR (a.FridaySchedule AND b.FridaySchedule) OR (a.SaturdaySchedule AND b.SaturdaySchedule))
 AND time(a.StartTime) < time(b.StartTime, '+'||b.Duration||' minutes') AND time(b.StartTime) < time(a.StartTime, '+'||a.Duration||' minutes');
