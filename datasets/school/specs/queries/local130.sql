-- local130: last names of the students who completed (ClassStatus = 2) an English class
-- (Subjects.CategoryID = 'ENG'), with a quintile from the share of completions with a grade at
-- least theirs: First (top 20%) .. Fifth, from highest to lowest.
-- Written from the question (no gold SQL). Reproduces gold variant local130_a.csv, 18 of 18
-- rows as a multiset (the grade column is kept, as in the CSV).
WITH e AS (SELECT st.StudLastName, s.Grade
           FROM Student_Schedules s JOIN Classes c USING (ClassID)
           JOIN Subjects u USING (SubjectID) JOIN Students st USING (StudentID)
           WHERE s.ClassStatus = 2 AND u.CategoryID = 'ENG'),
r AS (SELECT e.*, (SELECT count(*) FROM e e2 WHERE e2.Grade >= e.Grade) * 1.0
                  / (SELECT count(*) FROM e) AS pr
      FROM e)
SELECT StudLastName, Grade,
       CASE WHEN pr <= 0.2 THEN 'First' WHEN pr <= 0.4 THEN 'Second' WHEN pr <= 0.6 THEN 'Third'
            WHEN pr <= 0.8 THEN 'Fourth' ELSE 'Fifth' END AS QUINTILE
FROM r ORDER BY pr, StudLastName;
