-- local025: each match's highest over (bat runs + extras, over every innings), its bowler,
-- and the mean of those maxima across matches.
-- No gold SQL; written from the question. Reproduces all 568 rows of local025_a.csv: a tie
-- goes to the earlier innings and over, and the bowler is the one of the over's first ball.
WITH o AS (
    SELECT b.match_id, b.innings_no, b.over_id,
           sum(coalesce(s.runs_scored, 0) + coalesce(e.extra_runs, 0)) AS runs
    FROM ball_by_ball b
    LEFT JOIN batsman_scored s USING (match_id, over_id, ball_id, innings_no)
    LEFT JOIN extra_runs e USING (match_id, over_id, ball_id, innings_no)
    GROUP BY 1, 2, 3
),
top AS (
    SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY match_id
                                                ORDER BY runs DESC, innings_no, over_id) AS r
                   FROM o) WHERE r = 1
),
bw AS (
    SELECT match_id, innings_no, over_id, bowler FROM (
        SELECT *, row_number() OVER (PARTITION BY match_id, innings_no, over_id
                                     ORDER BY ball_id) AS r
        FROM ball_by_ball) WHERE r = 1
)
SELECT t.match_id, t.innings_no, t.over_id, bw.bowler AS bowler_id,
       p.player_name AS bowler_name, t.runs AS highest_over_runs,
       round(avg(t.runs) OVER (), 3) AS avg_highest_over_runs_across_matches
FROM top t JOIN bw USING (match_id, innings_no, over_id)
LEFT JOIN player p ON p.player_id = bw.bowler
ORDER BY t.match_id;
