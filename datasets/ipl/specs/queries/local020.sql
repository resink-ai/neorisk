-- local020: the bowler with the lowest bowling average per wicket taken.
-- No gold SQL; written from the question (docs/research/spider2/ipl.md, q5:local020).
-- Reproduces local020_a.csv: 53, AC Gilchrist, 0.00 (bat runs conceded over bowler's wickets).
WITH w AS (
    SELECT b.bowler AS p, count(*) AS n
    FROM wicket_taken w
    JOIN ball_by_ball b USING (match_id, over_id, ball_id, innings_no)
    WHERE w.kind_out NOT IN ('run out', 'retired hurt', 'obstructing the field')
    GROUP BY 1
),
r AS (
    SELECT b.bowler AS p, sum(coalesce(s.runs_scored, 0)) AS runs
    FROM ball_by_ball b
    LEFT JOIN batsman_scored s USING (match_id, over_id, ball_id, innings_no)
    GROUP BY 1
)
SELECT pl.player_id AS bowler_id, pl.player_name AS bowler_name,
       round(1.0 * r.runs / w.n, 2) AS bowling_average
FROM w JOIN r USING (p) JOIN player pl ON pl.player_id = w.p
ORDER BY bowling_average, bowler_id
LIMIT 1;
