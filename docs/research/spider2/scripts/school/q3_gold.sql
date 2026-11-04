-- name: local130
WITH e AS (SELECT st.StudLastName, s.Grade FROM Student_Schedules s JOIN Classes c USING (ClassID) JOIN Subjects u USING (SubjectID) JOIN Students st USING (StudentID)
           WHERE s.ClassStatus = 2 AND u.CategoryID = 'ENG'),
r AS (SELECT e.*, (SELECT count(*) FROM e e2 WHERE e2.Grade >= e.Grade) * 1.0 / (SELECT count(*) FROM e) AS pr FROM e)
SELECT StudLastName, Grade, CASE WHEN pr <= 0.2 THEN 'First' WHEN pr <= 0.4 THEN 'Second' WHEN pr <= 0.6 THEN 'Third' WHEN pr <= 0.8 THEN 'Fourth' ELSE 'Fifth' END AS QUINTILE
FROM r ORDER BY pr;
-- name: english_completions
SELECT count(*), count(DISTINCT StudentID) FROM Student_Schedules s JOIN Classes c USING (ClassID) JOIN Subjects u USING (SubjectID) WHERE s.ClassStatus=2 AND u.CategoryID='ENG';
-- name: categories
SELECT * FROM Categories;
