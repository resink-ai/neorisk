-- name: class_start_dates
SELECT StartDate, strftime('%w', StartDate) dow, count(*) classes, (SELECT count(*) FROM Student_Schedules s WHERE s.ClassID IN (SELECT ClassID FROM Classes c2 WHERE c2.StartDate=c.StartDate)) enrolments FROM Classes c GROUP BY 1;
-- name: class_formats
SELECT length(StartDate), length(StartTime), count(*) FROM Classes GROUP BY 1,2;
-- name: durations
SELECT Duration, count(*) FROM Classes GROUP BY 1;
-- name: days_pattern
SELECT MondaySchedule||TuesdaySchedule||WednesdaySchedule||ThursdaySchedule||FridaySchedule||SaturdaySchedule pat, count(*), group_concat(DISTINCT Duration), group_concat(DISTINCT Credits) FROM Classes GROUP BY 1;
-- name: credits_vs_days
SELECT Credits, (MondaySchedule+TuesdaySchedule+WednesdaySchedule+ThursdaySchedule+FridaySchedule+SaturdaySchedule) ndays, Duration, count(*) FROM Classes GROUP BY 1,2,3;
-- name: room_conflicts
-- two classes in the same room, same start date, overlapping days and times
SELECT count(*) FROM Classes a JOIN Classes b ON a.ClassRoomID=b.ClassRoomID AND a.ClassID<b.ClassID AND a.StartDate=b.StartDate
 AND ((a.MondaySchedule AND b.MondaySchedule) OR (a.TuesdaySchedule AND b.TuesdaySchedule) OR (a.WednesdaySchedule AND b.WednesdaySchedule) OR (a.ThursdaySchedule AND b.ThursdaySchedule) OR (a.FridaySchedule AND b.FridaySchedule) OR (a.SaturdaySchedule AND b.SaturdaySchedule))
 AND time(a.StartTime) < time(b.StartTime, '+'||b.Duration||' minutes') AND time(b.StartTime) < time(a.StartTime, '+'||a.Duration||' minutes');
-- name: status_dist
SELECT s.ClassStatus, d.ClassStatusDescription, count(*), min(Grade), max(Grade), sum(Grade=0) zero FROM Student_Schedules s JOIN Student_Class_Status d USING (ClassStatus) GROUP BY 1;
-- name: status_by_start_date
SELECT c.StartDate, s.ClassStatus, count(*) FROM Student_Schedules s JOIN Classes c USING (ClassID) GROUP BY 1,2;
-- name: grade_decimals
SELECT CASE WHEN Grade = round(Grade,2) THEN 'le2dp' ELSE 'more' END k, count(*) FROM Student_Schedules GROUP BY 1;
-- name: grade_print
SELECT printf('%.17g', Grade) p, CAST(Grade AS TEXT) t, count(*) FROM Student_Schedules GROUP BY 1 HAVING p <> t LIMIT 10;
-- name: gpa_vs_grades
-- StudGPA vs mean grade of completed classes (credit-weighted or not)
SELECT st.StudentID, st.StudGPA, round(avg(CASE WHEN s.ClassStatus=2 THEN Grade END),3) avg_completed,
       round(sum(CASE WHEN s.ClassStatus=2 THEN Grade*c.Credits END)/sum(CASE WHEN s.ClassStatus=2 THEN c.Credits END),3) wavg_completed,
       round(avg(Grade),3) avg_all, count(s.ClassID) n, sum(s.ClassStatus=2) n_completed
FROM Students st LEFT JOIN Student_Schedules s USING (StudentID) LEFT JOIN Classes c USING (ClassID) GROUP BY 1;
-- name: gpa_print
SELECT StudentID, StudGPA, printf('%.17g', StudGPA) FROM Students;
-- name: salary_print
SELECT Salary, count(*) FROM Staff GROUP BY 1;
-- name: staff_hired
SELECT min(DateHired), max(DateHired), sum(length(DateHired)=10) FROM Staff;
-- name: proficiency
SELECT ProficiencyRating, count(*) FROM Faculty_Subjects GROUP BY 1;
-- name: enrolments_per_student
SELECT StudentID, count(*), sum(ClassStatus=1) enrolled, sum(ClassStatus=2) completed, sum(ClassStatus=3) withdrew FROM Student_Schedules GROUP BY 1;
-- name: student_time_clash
SELECT count(*) FROM Student_Schedules x JOIN Student_Schedules y ON x.StudentID=y.StudentID AND x.ClassID<y.ClassID JOIN Classes a ON a.ClassID=x.ClassID JOIN Classes b ON b.ClassID=y.ClassID
 WHERE a.StartDate=b.StartDate AND ((a.MondaySchedule AND b.MondaySchedule) OR (a.TuesdaySchedule AND b.TuesdaySchedule) OR (a.WednesdaySchedule AND b.WednesdaySchedule) OR (a.ThursdaySchedule AND b.ThursdaySchedule) OR (a.FridaySchedule AND b.FridaySchedule))
 AND time(a.StartTime) < time(b.StartTime, '+'||b.Duration||' minutes') AND time(b.StartTime) < time(a.StartTime, '+'||a.Duration||' minutes');
-- name: class_id_vs_start
SELECT substr(ClassID,1,1) k, group_concat(DISTINCT StartDate), count(*) FROM Classes GROUP BY 1;
