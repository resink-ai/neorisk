-- name: local022_gold_sql
WITH player_runs AS (SELECT bbb.striker AS player_id, bbb.match_id, SUM(bsc.runs_scored) AS total_runs FROM ball_by_ball AS bbb
  JOIN batsman_scored AS bsc ON bbb.match_id = bsc.match_id AND bbb.over_id = bsc.over_id AND bbb.ball_id = bsc.ball_id AND bbb.innings_no = bsc.innings_no
  GROUP BY bbb.striker, bbb.match_id HAVING SUM(bsc.runs_scored) >= 100),
losing_teams AS (SELECT match_id, CASE WHEN match_winner = team_1 THEN team_2 ELSE team_1 END AS loser FROM match),
players_in_losing_teams AS (SELECT pr.player_id, pr.match_id FROM player_runs AS pr JOIN losing_teams AS lt ON pr.match_id = lt.match_id
  JOIN player_match AS pm ON pr.player_id = pm.player_id AND pr.match_id = pm.match_id AND lt.loser = pm.team_id)
SELECT DISTINCT p.player_name FROM player AS p JOIN players_in_losing_teams AS plt ON p.player_id = plt.player_id ORDER BY p.player_name;
-- name: local023_gold_sql
WITH runs_scored AS (SELECT bb.striker AS player_id, bb.match_id, bs.runs_scored AS runs FROM ball_by_ball AS bb
  JOIN batsman_scored AS bs ON bb.match_id = bs.match_id AND bb.over_id = bs.over_id AND bb.ball_id = bs.ball_id AND bb.innings_no = bs.innings_no
  WHERE bb.match_id IN (SELECT match_id FROM match WHERE season_id = 5)),
total_runs AS (SELECT player_id, match_id, SUM(runs) AS total_runs FROM runs_scored GROUP BY player_id, match_id),
batting_averages AS (SELECT player_id, SUM(total_runs) AS runs, COUNT(match_id) AS num_matches, ROUND(SUM(total_runs) / CAST(COUNT(match_id) AS FLOAT), 3) AS batting_avg
  FROM total_runs GROUP BY player_id ORDER BY batting_avg DESC LIMIT 5)
SELECT p.player_name, b.batting_avg FROM player AS p JOIN batting_averages AS b ON p.player_id = b.player_id ORDER BY b.batting_avg DESC;
-- name: local023_csv_variant
-- CSV: avg_runs_per_match = runs / matches in player_match for season 5; batting_average = runs / dismissals
WITH r AS (SELECT b.striker p, sum(s.runs_scored) runs FROM ball_by_ball b JOIN batsman_scored s USING (match_id,over_id,ball_id,innings_no) JOIN match m USING (match_id) WHERE m.season_id=5 GROUP BY 1),
g AS (SELECT pm.player_id p, count(*) games FROM player_match pm JOIN match m USING (match_id) WHERE m.season_id=5 GROUP BY 1),
d AS (SELECT w.player_out p, count(*) outs FROM wicket_taken w JOIN match m USING (match_id) WHERE m.season_id=5 GROUP BY 1)
SELECT pl.player_name, round(1.0*r.runs/g.games,4) avg_runs_per_match, round(1.0*r.runs/d.outs,4) batting_average FROM r JOIN g USING (p) JOIN d USING (p) JOIN player pl ON pl.player_id=r.p
ORDER BY 2 DESC LIMIT 5;
-- name: local228
WITH bat AS (SELECT m.season_id, b.striker p, sum(s.runs_scored) v FROM ball_by_ball b JOIN batsman_scored s USING (match_id,over_id,ball_id,innings_no) JOIN match m USING (match_id) GROUP BY 1,2),
bowl AS (SELECT m.season_id, b.bowler p, count(*) v FROM wicket_taken w JOIN ball_by_ball b USING (match_id,over_id,ball_id,innings_no) JOIN match m USING (match_id)
  WHERE w.kind_out NOT IN ('run out','hit wicket','retired hurt') GROUP BY 1,2),
rb AS (SELECT *, row_number() OVER (PARTITION BY season_id ORDER BY v DESC, p) r FROM bat), rw AS (SELECT *, row_number() OVER (PARTITION BY season_id ORDER BY v DESC, p) r FROM bowl)
SELECT rb.season_id, pb.player_name, rb.v, pw.player_name, rw.v FROM rb JOIN rw ON rb.season_id=rw.season_id AND rb.r=rw.r
LEFT JOIN player pb ON pb.player_id=rb.p LEFT JOIN player pw ON pw.player_id=rw.p WHERE rb.r<=3 ORDER BY rb.season_id, rb.r;
-- name: local026
WITH o AS (SELECT b.match_id, b.innings_no, b.over_id, b.bowler, sum(coalesce(s.runs_scored,0)+coalesce(e.extra_runs,0)) runs FROM ball_by_ball b
  LEFT JOIN batsman_scored s USING (match_id,over_id,ball_id,innings_no) LEFT JOIN extra_runs e USING (match_id,over_id,ball_id,innings_no) GROUP BY 1,2,3,4),
mx AS (SELECT *, rank() OVER (PARTITION BY match_id ORDER BY runs DESC) r FROM o)
SELECT p.player_name, mx.match_id, mx.runs FROM mx JOIN player p ON p.player_id=mx.bowler WHERE r=1 ORDER BY runs DESC LIMIT 5;
-- name: local021
WITH pm AS (SELECT b.striker p, b.match_id, sum(s.runs_scored) r FROM ball_by_ball b JOIN batsman_scored s USING (match_id,over_id,ball_id,innings_no) GROUP BY 1,2)
SELECT avg(t) FROM (SELECT p, sum(r) t FROM pm GROUP BY p HAVING max(r) > 50);
-- name: local020
WITH w AS (SELECT b.bowler p, count(*) n FROM wicket_taken w JOIN ball_by_ball b USING (match_id,over_id,ball_id,innings_no) WHERE w.kind_out NOT IN ('run out','retired hurt','obstructing the field') GROUP BY 1),
r AS (SELECT b.bowler p, sum(coalesce(s.runs_scored,0)) runs FROM ball_by_ball b LEFT JOIN batsman_scored s USING (match_id,over_id,ball_id,innings_no) GROUP BY 1)
SELECT pl.player_id, pl.player_name, round(1.0*r.runs/w.n,2) avg, r.runs, w.n FROM w JOIN r USING (p) JOIN player pl ON pl.player_id=p ORDER BY 3 LIMIT 3;
