-- local229: each match's highest partnership: both batters' ids and runs off the bat, the
-- higher scorer (on a tie, the higher id) first; ties for the top give several rows.
-- No gold SQL; written from the question. Reproduces all 577 rows of local229_b.csv.
WITH d AS (
    SELECT b.match_id, b.innings_no, b.striker, b.non_striker,
           coalesce(s.runs_scored, 0) AS runs
    FROM ball_by_ball b
    LEFT JOIN batsman_scored s USING (match_id, over_id, ball_id, innings_no)
),
pr AS (
    SELECT match_id, innings_no,
           min(striker, non_striker) AS lo, max(striker, non_striker) AS hi,
           sum(CASE WHEN striker = min(striker, non_striker) THEN runs ELSE 0 END) AS lo_runs,
           sum(CASE WHEN striker = max(striker, non_striker) THEN runs ELSE 0 END) AS hi_runs,
           sum(runs) AS total
    FROM d GROUP BY 1, 2, 3, 4
),
top AS (SELECT *, rank() OVER (PARTITION BY match_id ORDER BY total DESC) AS r FROM pr)
SELECT match_id,
       CASE WHEN hi_runs >= lo_runs THEN hi ELSE lo END AS player1_id,
       CASE WHEN hi_runs >= lo_runs THEN hi_runs ELSE lo_runs END AS player1_runs,
       CASE WHEN hi_runs >= lo_runs THEN lo ELSE hi END AS player2_id,
       CASE WHEN hi_runs >= lo_runs THEN lo_runs ELSE hi_runs END AS player2_runs,
       total AS total_partnership_runs
FROM top WHERE r = 1
ORDER BY match_id, player1_id, player2_id;
