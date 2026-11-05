-- name: spring_is_fall_plus_3000
SELECT count(*) spring, sum(f.ClassID IS NOT NULL) has_fall_twin,
       sum(f.SubjectID=s.SubjectID AND f.ClassRoomID=s.ClassRoomID AND f.Credits=s.Credits AND f.StartTime=s.StartTime AND f.Duration=s.Duration
           AND f.MondaySchedule=s.MondaySchedule AND f.TuesdaySchedule=s.TuesdaySchedule AND f.WednesdaySchedule=s.WednesdaySchedule
           AND f.ThursdaySchedule=s.ThursdaySchedule AND f.FridaySchedule=s.FridaySchedule AND f.SaturdaySchedule=s.SaturdaySchedule) identical_but_date,
       sum(julianday(s.StartDate)-julianday(f.StartDate) = 126) date_plus_126
FROM Classes s LEFT JOIN Classes f ON f.ClassID = s.ClassID - 3000 WHERE s.StartDate >= '2018-01-01';
-- name: spring_without_twin
SELECT s.ClassID, s.SubjectID, s.StartDate FROM Classes s WHERE s.StartDate >= '2018-01-01' AND s.ClassID - 3000 NOT IN (SELECT ClassID FROM Classes WHERE StartDate < '2018-01-01');
-- name: fall_without_twin
SELECT f.ClassID, f.SubjectID, f.StartDate FROM Classes f WHERE f.StartDate < '2018-01-01' AND f.ClassID + 3000 NOT IN (SELECT ClassID FROM Classes);
-- name: twin_differences
SELECT s.ClassID, f.SubjectID fs, s.SubjectID ss, f.ClassRoomID fr, s.ClassRoomID sr, f.StartTime ft, s.StartTime st, f.Duration fd, s.Duration sd FROM Classes s JOIN Classes f ON f.ClassID = s.ClassID - 3000
WHERE s.StartDate >= '2018-01-01' AND NOT (f.SubjectID=s.SubjectID AND f.ClassRoomID=s.ClassRoomID AND f.Credits=s.Credits AND f.StartTime=s.StartTime AND f.Duration=s.Duration
           AND f.MondaySchedule=s.MondaySchedule AND f.TuesdaySchedule=s.TuesdaySchedule AND f.WednesdaySchedule=s.WednesdaySchedule
           AND f.ThursdaySchedule=s.ThursdaySchedule AND f.FridaySchedule=s.FridaySchedule AND f.SaturdaySchedule=s.SaturdaySchedule);
-- name: faculty_twins
SELECT count(*) spring_fc, sum(EXISTS (SELECT 1 FROM Faculty_Classes f WHERE f.ClassID = s.ClassID - 3000 AND f.StaffID = s.StaffID)) same_teacher FROM Faculty_Classes s WHERE s.ClassID >= 4000;
-- name: enrolment_pattern
-- does a student take the spring twin of a class they completed in fall?
SELECT count(*) FROM Student_Schedules a JOIN Student_Schedules b ON a.StudentID=b.StudentID AND b.ClassID=a.ClassID+3000;
-- name: twin_date_offsets
SELECT f.StartDate, s.StartDate, julianday(s.StartDate)-julianday(f.StartDate) d, count(*) FROM Classes s JOIN Classes f ON f.ClassID = s.ClassID - 3000 WHERE s.StartDate >= '2018-01-01' GROUP BY 1,2;
-- name: description_length
SELECT max(length(SubjectDescription)), min(length(SubjectDescription)) FROM Subjects;
