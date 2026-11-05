-- name: sqlite_sequence
SELECT * FROM sqlite_sequence;
-- name: fk_orphans
SELECT 'class_rooms->buildings' fk, count(*) n FROM Class_Rooms WHERE BuildingCode NOT IN (SELECT BuildingCode FROM Buildings)
UNION ALL SELECT 'classes->subjects', count(*) FROM Classes WHERE SubjectID NOT IN (SELECT SubjectID FROM Subjects)
UNION ALL SELECT 'classes->class_rooms', count(*) FROM Classes WHERE ClassRoomID NOT IN (SELECT ClassRoomID FROM Class_Rooms)
UNION ALL SELECT 'departments chair->staff', count(*) FROM Departments WHERE DeptChair NOT IN (SELECT StaffID FROM Staff)
UNION ALL SELECT 'categories->departments', count(*) FROM Categories WHERE DepartmentID NOT IN (SELECT DepartmentID FROM Departments)
UNION ALL SELECT 'faculty->staff', count(*) FROM Faculty WHERE StaffID NOT IN (SELECT StaffID FROM Staff)
UNION ALL SELECT 'fac_cat->faculty', count(*) FROM Faculty_Categories WHERE StaffID NOT IN (SELECT StaffID FROM Faculty)
UNION ALL SELECT 'fac_cat->categories', count(*) FROM Faculty_Categories WHERE CategoryID NOT IN (SELECT CategoryID FROM Categories)
UNION ALL SELECT 'fac_classes->classes', count(*) FROM Faculty_Classes WHERE ClassID NOT IN (SELECT ClassID FROM Classes)
UNION ALL SELECT 'fac_classes->staff', count(*) FROM Faculty_Classes WHERE StaffID NOT IN (SELECT StaffID FROM Staff)
UNION ALL SELECT 'fac_classes->faculty', count(*) FROM Faculty_Classes WHERE StaffID NOT IN (SELECT StaffID FROM Faculty)
UNION ALL SELECT 'fac_subj->faculty', count(*) FROM Faculty_Subjects WHERE StaffID NOT IN (SELECT StaffID FROM Faculty)
UNION ALL SELECT 'fac_subj->subjects', count(*) FROM Faculty_Subjects WHERE SubjectID NOT IN (SELECT SubjectID FROM Subjects)
UNION ALL SELECT 'sched->students', count(*) FROM Student_Schedules WHERE StudentID NOT IN (SELECT StudentID FROM Students)
UNION ALL SELECT 'sched->classes', count(*) FROM Student_Schedules WHERE ClassID NOT IN (SELECT ClassID FROM Classes)
UNION ALL SELECT 'sched->status', count(*) FROM Student_Schedules WHERE ClassStatus NOT IN (SELECT ClassStatus FROM Student_Class_Status)
UNION ALL SELECT 'students->majors', count(*) FROM Students WHERE StudMajor NOT IN (SELECT MajorID FROM Majors)
UNION ALL SELECT 'subjects->categories', count(*) FROM Subjects WHERE CategoryID NOT IN (SELECT CategoryID FROM Categories)
UNION ALL SELECT 'subjects prereq->code', count(*) FROM Subjects WHERE SubjectPreReq NOT IN (SELECT SubjectCode FROM Subjects);
-- name: coverage
SELECT 'classes with students' k, count(DISTINCT ClassID) FROM Student_Schedules
UNION ALL SELECT 'classes with faculty', count(DISTINCT ClassID) FROM Faculty_Classes
UNION ALL SELECT 'classes w/o faculty', count(*) FROM Classes WHERE ClassID NOT IN (SELECT ClassID FROM Faculty_Classes)
UNION ALL SELECT 'classes with >1 faculty', count(*) FROM (SELECT ClassID FROM Faculty_Classes GROUP BY 1 HAVING count(*)>1)
UNION ALL SELECT 'students w/o schedule', count(*) FROM Students WHERE StudentID NOT IN (SELECT StudentID FROM Student_Schedules)
UNION ALL SELECT 'staff not faculty', count(*) FROM Staff WHERE StaffID NOT IN (SELECT StaffID FROM Faculty)
UNION ALL SELECT 'faculty w/o class', count(*) FROM Faculty WHERE StaffID NOT IN (SELECT StaffID FROM Faculty_Classes)
UNION ALL SELECT 'subjects w/o class', count(*) FROM Subjects WHERE SubjectID NOT IN (SELECT SubjectID FROM Classes)
UNION ALL SELECT 'rooms w/o class', count(*) FROM Class_Rooms WHERE ClassRoomID NOT IN (SELECT ClassRoomID FROM Classes)
UNION ALL SELECT 'buildings w/o room', count(*) FROM Buildings WHERE BuildingCode NOT IN (SELECT BuildingCode FROM Class_Rooms)
UNION ALL SELECT 'categories w/o subject', count(*) FROM Categories WHERE CategoryID NOT IN (SELECT CategoryID FROM Subjects)
UNION ALL SELECT 'majors w/o student', count(*) FROM Majors WHERE MajorID NOT IN (SELECT StudMajor FROM Students WHERE StudMajor IS NOT NULL);
-- name: staff_not_faculty
SELECT StaffID, StfFirstName, StfLastname, Position, (SELECT count(*) FROM Faculty_Classes f WHERE f.StaffID=s.StaffID) classes FROM Staff s WHERE StaffID NOT IN (SELECT StaffID FROM Faculty);
-- name: class_teacher_subject_consistency
-- the teacher of a class has the class's subject in Faculty_Subjects? and its category in Faculty_Categories?
SELECT count(*) fc_rows, sum(EXISTS (SELECT 1 FROM Faculty_Subjects s WHERE s.StaffID=f.StaffID AND s.SubjectID=c.SubjectID)) has_subject,
       sum(EXISTS (SELECT 1 FROM Faculty_Categories k JOIN Subjects u ON u.CategoryID=k.CategoryID WHERE k.StaffID=f.StaffID AND u.SubjectID=c.SubjectID)) has_category
FROM Faculty_Classes f JOIN Classes c USING (ClassID);
-- name: fac_subjects_categories_consistency
SELECT count(*) rows_, sum(EXISTS (SELECT 1 FROM Faculty_Categories k WHERE k.StaffID=s.StaffID AND k.CategoryID=u.CategoryID)) cat_listed FROM Faculty_Subjects s JOIN Subjects u USING (SubjectID);
-- name: chairs_are_faculty
SELECT d.*, (SELECT count(*) FROM Faculty f WHERE f.StaffID=d.DeptChair) is_faculty FROM Departments d;
-- name: id_ranges
SELECT 'ClassID' k, group_concat(DISTINCT substr(ClassID,1,1)) FROM Classes UNION ALL SELECT 'room bldg prefix', group_concat(DISTINCT BuildingCode||substr(ClassRoomID,1,1)) FROM Class_Rooms;
-- name: classroom_id_encodes_building
SELECT BuildingCode, min(ClassRoomID), max(ClassRoomID), count(*) FROM Class_Rooms GROUP BY 1;
-- name: subject_code_prefix_is_category
SELECT sum(substr(SubjectCode,1,instr(SubjectCode,' ')-1) = CategoryID) ok, count(*) FROM Subjects;
-- name: prereqs
SELECT SubjectCode, SubjectPreReq FROM Subjects WHERE SubjectPreReq IS NOT NULL;
