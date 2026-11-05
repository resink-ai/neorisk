-- local096: per year (the last 4 characters of Movie.year), the number of movies and the
-- percentage whose cast is exclusively female; Male or unknown gender counts as non-female.
-- Written from the question (no gold SQL). Reproduces gold variant local096_a.csv, 78 of 78 rows.
WITH my AS (SELECT MID, CAST(substr(year, -4) AS INTEGER) AS y FROM Movie),
g AS (SELECT DISTINCT PID, Gender FROM Person WHERE PID IS NOT NULL),
mc AS (SELECT c.MID, sum(CASE WHEN g.Gender = 'Female' THEN 0 ELSE 1 END) AS nonfemale
       FROM M_Cast c LEFT JOIN g ON g.PID = trim(c.PID) GROUP BY c.MID)
SELECT my.y AS YEAR, count(*) AS TOTAL_MOVIES,
       round(100.0 * sum(mc.nonfemale = 0) / count(*), 2) AS PERCENTAGE_EXCLUSIVELY_FEMALE
FROM my LEFT JOIN mc USING (MID) GROUP BY my.y ORDER BY my.y;
