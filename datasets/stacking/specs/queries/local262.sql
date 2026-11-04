-- local262: problems whose count of strong (name, version, step) results, over steps 1-3,
-- exceeds their number of solution rows. Strong: the max non-Stack test score at a step is
-- below the Stack's test score, which is the source view stack_ok's 'strong' status.
-- Written from the question (no gold SQL), over the replayed view stack_ok. Reproduces gold
-- variant local262_a.csv, 7 of 7 names.
SELECT k.name
FROM (SELECT name, count(*) AS n FROM stack_ok WHERE status = 'strong' GROUP BY name) k
JOIN (SELECT name, count(*) AS n FROM solution GROUP BY name) s ON s.name = k.name
WHERE k.n > s.n
ORDER BY k.name;
