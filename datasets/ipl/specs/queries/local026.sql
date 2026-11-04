-- local026: the top 3 bowlers among each match's most expensive over (bat runs + extras).
-- No gold SQL; written from the question (docs/research/spider2/ipl.md, q5:local026).
-- Reproduces local026_a.csv: P Parameswaran 501252 37; P Awana 734052 33; RS Bopara 419144 33.
WITH o AS (
    SELECT b.match_id, b.innings_no, b.over_id, b.bowler,
           sum(coalesce(s.runs_scored, 0) + coalesce(e.extra_runs, 0)) AS runs
    FROM ball_by_ball b
    LEFT JOIN batsman_scored s USING (match_id, over_id, ball_id, innings_no)
    LEFT JOIN extra_runs e USING (match_id, over_id, ball_id, innings_no)
    GROUP BY 1, 2, 3, 4
),
mx AS (SELECT *, rank() OVER (PARTITION BY match_id ORDER BY runs DESC) AS r FROM o)
SELECT p.player_name AS bowler_name, mx.match_id, mx.runs AS runs_in_over
FROM mx JOIN player p ON p.player_id = mx.bowler
WHERE mx.r = 1
ORDER BY runs_in_over DESC, bowler_name
LIMIT 3;
