-- local259: each player's career line: role, runs, matches, dismissals, average, best score,
-- 30/50/100 counts, balls faced, strike rate, wickets, economy and best bowling.
-- No gold SQL; written from the question. Reproduces all 468 rows of local259_c.csv: the
-- extra runs are ignored, so a ball counts only when it has a batsman_scored row.
WITH d AS (
    SELECT b.match_id, b.striker, b.bowler, s.runs_scored AS runs
    FROM ball_by_ball b
    JOIN batsman_scored s USING (match_id, over_id, ball_id, innings_no)
),
wk AS (
    SELECT b.bowler, b.match_id, count(*) AS w
    FROM wicket_taken w
    JOIN ball_by_ball b USING (match_id, over_id, ball_id, innings_no)
    WHERE w.kind_out IN ('caught', 'bowled', 'lbw', 'stumped', 'caught and bowled', 'hit wicket')
    GROUP BY 1, 2
),
roles AS (
    SELECT player_id, role FROM (
        SELECT player_id, role,
               row_number() OVER (PARTITION BY player_id ORDER BY count(*) DESC, role) AS r
        FROM player_match GROUP BY player_id, role) WHERE r = 1
),
games AS (SELECT player_id, count(*) AS n FROM player_match GROUP BY 1),
bat_m AS (SELECT striker AS player_id, match_id, sum(runs) AS r, count(*) AS balls
          FROM d GROUP BY 1, 2),
bat AS (
    SELECT player_id, sum(r) AS runs, max(r) AS hs, sum(balls) AS balls,
           sum(r >= 30) AS m30, sum(r >= 50) AS m50, sum(r >= 100) AS m100
    FROM bat_m GROUP BY 1
),
outs AS (SELECT player_out AS player_id, count(*) AS n FROM wicket_taken GROUP BY 1),
bowl_m AS (
    SELECT c.bowler AS player_id, c.match_id, coalesce(wk.w, 0) AS w, c.r, c.balls
    FROM (SELECT bowler, match_id, sum(runs) AS r, count(*) AS balls FROM d GROUP BY 1, 2) c
    LEFT JOIN wk USING (bowler, match_id)
),
bowl AS (SELECT player_id, sum(w) AS w, sum(r) AS r, sum(balls) AS balls FROM bowl_m GROUP BY 1),
best AS (
    SELECT player_id, w || '-' || r AS best FROM (
        SELECT *, row_number() OVER (PARTITION BY player_id ORDER BY w DESC, r) AS k
        FROM bowl_m) WHERE k = 1
)
SELECT p.player_id, p.player_name, ro.role AS most_frequent_role, p.batting_hand,
       p.bowling_skill, coalesce(bt.runs, 0) AS total_runs, coalesce(g.n, 0) AS total_matches,
       coalesce(o.n, 0) AS total_dismissals,
       1.0 * coalesce(bt.runs, 0) / o.n AS batting_average,
       coalesce(bt.hs, 0) AS highest_score, coalesce(bt.m30, 0) AS matches_30_plus,
       coalesce(bt.m50, 0) AS matches_50_plus, coalesce(bt.m100, 0) AS matches_100_plus,
       coalesce(bt.balls, 0) AS total_balls_faced, 100.0 * bt.runs / bt.balls AS strike_rate,
       coalesce(bw.w, 0) AS total_wickets, 6.0 * bw.r / bw.balls AS economy_rate,
       be.best AS best_bowling
FROM player p
LEFT JOIN roles ro USING (player_id) LEFT JOIN games g USING (player_id)
LEFT JOIN bat bt USING (player_id) LEFT JOIN outs o USING (player_id)
LEFT JOIN bowl bw USING (player_id) LEFT JOIN best be USING (player_id)
ORDER BY p.player_id;
