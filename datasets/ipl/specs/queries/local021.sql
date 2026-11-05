-- local021: the average career runs of the strikers who scored more than 50 in some match.
-- No gold SQL; written from the question (docs/research/spider2/ipl.md, q5:local021).
-- Reproduces local021_a.csv: 1130.516129.
WITH pm AS (
    SELECT b.striker AS p, b.match_id, sum(s.runs_scored) AS r
    FROM ball_by_ball b
    JOIN batsman_scored s USING (match_id, over_id, ball_id, innings_no)
    GROUP BY 1, 2
)
SELECT avg(t) AS avg_total_runs
FROM (SELECT p, sum(r) AS t FROM pm GROUP BY p HAVING max(r) > 50);
