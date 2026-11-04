-- local258: each bowler's wickets (bowler's dismissals only), economy (bat runs per 6 legal
-- balls), strike rate (legal balls per wicket) and best match ("wickets-runs").
-- No gold SQL; written from the question. Reproduces all 329 rows of local258_b.csv (2
-- decimals, rounded half up); local258_c/d also list placeholder player 35.
WITH d AS (
    SELECT b.match_id, b.bowler, coalesce(s.runs_scored, 0) AS runs,
           CASE WHEN e.extra_type IN ('wides', 'noballs') THEN 0 ELSE 1 END AS legal,
           CASE WHEN w.kind_out IN ('caught', 'bowled', 'lbw', 'stumped', 'caught and bowled',
                                    'hit wicket') THEN 1 ELSE 0 END AS wk
    FROM ball_by_ball b
    LEFT JOIN batsman_scored s USING (match_id, over_id, ball_id, innings_no)
    LEFT JOIN extra_runs e USING (match_id, over_id, ball_id, innings_no)
    LEFT JOIN wicket_taken w USING (match_id, over_id, ball_id, innings_no)
),
tot AS (SELECT bowler, sum(wk) AS wickets, sum(runs) AS runs, sum(legal) AS balls
        FROM d GROUP BY 1),
pm AS (SELECT bowler, match_id, sum(wk) AS w, sum(runs) AS r FROM d GROUP BY 1, 2),
best AS (SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY bowler ORDER BY w DESC, r)
                                  AS k FROM pm) WHERE k = 1)
SELECT p.player_name AS bowler_name, t.wickets AS total_wickets,
       round(600.0 * t.runs / t.balls) / 100 AS economy_rate,
       round(100.0 * t.balls / nullif(t.wickets, 0)) / 100 AS strike_rate,
       b.w || '-' || b.r AS best_bowling_performance
FROM tot t JOIN best b USING (bowler) JOIN player p ON p.player_id = t.bowler
ORDER BY total_wickets DESC, economy_rate, bowler_name;
