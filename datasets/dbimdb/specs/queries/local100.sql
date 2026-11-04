-- local100: actors with a "Shahrukh number" of 2: in a film with someone who acted with
-- Shah Rukh Khan (nm0451321), but never in a film with him.
-- Written from the question (no gold SQL). Reproduces gold variant local100_a.csv (25698).
WITH srk AS (SELECT DISTINCT PID FROM Person WHERE trim(Name) IN ('Shah Rukh Khan', 'Shahrukh Khan')),
c AS (SELECT DISTINCT MID, trim(PID) AS PID FROM M_Cast WHERE PID IS NOT NULL),
s1 AS (SELECT DISTINCT b.PID FROM c a JOIN c b ON a.MID = b.MID
       WHERE a.PID IN (SELECT PID FROM srk) AND b.PID NOT IN (SELECT PID FROM srk)),
s2 AS (SELECT DISTINCT b.PID FROM c a JOIN c b ON a.MID = b.MID
       WHERE a.PID IN (SELECT PID FROM s1))
SELECT count(*) AS "COUNT(DISTINCT PID)" FROM s2
WHERE PID NOT IN (SELECT PID FROM s1) AND PID NOT IN (SELECT PID FROM srk);
