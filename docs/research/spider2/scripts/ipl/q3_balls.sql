-- name: er_without_ball
SELECT * FROM extra_runs s WHERE NOT EXISTS (SELECT 1 FROM ball_by_ball b WHERE b.match_id=s.match_id AND b.over_id=s.over_id AND b.ball_id=s.ball_id AND b.innings_no=s.innings_no);
-- name: er_without_ball_neighbours
SELECT b.*, bs.runs_scored FROM ball_by_ball b LEFT JOIN batsman_scored bs USING (match_id,over_id,ball_id,innings_no)
WHERE (b.match_id, b.innings_no, b.over_id) IN (SELECT match_id, innings_no, over_id FROM extra_runs s WHERE NOT EXISTS (SELECT 1 FROM ball_by_ball b WHERE b.match_id=s.match_id AND b.over_id=s.over_id AND b.ball_id=s.ball_id AND b.innings_no=s.innings_no)) ORDER BY ball_id;
-- name: mixed_team_innings
SELECT match_id, innings_no, team_batting, team_bowling, count(*), min(over_id), max(over_id) FROM ball_by_ball
WHERE (match_id, innings_no) IN (SELECT match_id, innings_no FROM ball_by_ball GROUP BY 1,2 HAVING count(DISTINCT team_batting)>1) GROUP BY 1,2,3,4;
-- name: ball_players_not_in_pm_by_match
SELECT b.match_id, count(*) FROM ball_by_ball b WHERE NOT EXISTS (SELECT 1 FROM player_match p WHERE p.match_id=b.match_id AND p.player_id=b.striker AND p.team_id=b.team_batting) GROUP BY 1;
-- name: ball_players_not_in_pm_any_team
SELECT count(*) FROM ball_by_ball b WHERE NOT EXISTS (SELECT 1 FROM player_match p WHERE p.match_id=b.match_id AND p.player_id=b.striker);
-- name: ball_id_per_over
SELECT ball_id, count(*) FROM ball_by_ball GROUP BY 1;
-- name: balls_per_over_dist
SELECT n, count(*) FROM (SELECT match_id, innings_no, over_id, count(*) n FROM ball_by_ball GROUP BY 1,2,3) GROUP BY 1;
-- name: legal_balls_per_over
SELECT legal, count(*) FROM (SELECT b.match_id, b.innings_no, b.over_id, sum(coalesce(er.extra_type NOT IN ('wides','noballs'),1)) legal
 FROM ball_by_ball b LEFT JOIN extra_runs er USING (match_id,over_id,ball_id,innings_no) GROUP BY 1,2,3) GROUP BY 1;
-- name: ball_id_gaps
SELECT count(*) overs_with_gaps FROM (SELECT match_id, innings_no, over_id FROM ball_by_ball GROUP BY 1,2,3 HAVING max(ball_id) <> count(*) OR min(ball_id)<>1);
-- name: ball_id_gap_detail
SELECT match_id, innings_no, over_id, group_concat(ball_id) FROM (SELECT * FROM ball_by_ball ORDER BY ball_id) GROUP BY 1,2,3 HAVING max(ball_id) <> count(*) OR min(ball_id)<>1 LIMIT 30;
-- name: over_gaps
SELECT count(*) innings_with_over_gaps FROM (SELECT match_id, innings_no FROM ball_by_ball GROUP BY 1,2 HAVING max(over_id) <> count(DISTINCT over_id));
-- name: over_gap_detail
SELECT match_id, innings_no, count(DISTINCT over_id), max(over_id) FROM ball_by_ball GROUP BY 1,2 HAVING max(over_id) <> count(DISTINCT over_id);
-- name: overs_per_innings
SELECT innings_no, max_over, count(*) FROM (SELECT match_id, innings_no, max(over_id) max_over FROM ball_by_ball GROUP BY 1,2) GROUP BY 1,2 ORDER BY 1,2;
-- name: bowler_per_over
SELECT n, count(*) FROM (SELECT match_id, innings_no, over_id, count(DISTINCT bowler) n FROM ball_by_ball GROUP BY 1,2,3) GROUP BY 1;
-- name: consecutive_overs_same_bowler
SELECT count(*) FROM (SELECT match_id, innings_no, over_id, min(bowler) b FROM ball_by_ball GROUP BY 1,2,3 HAVING count(DISTINCT bowler)=1) x
JOIN (SELECT match_id, innings_no, over_id, min(bowler) b FROM ball_by_ball GROUP BY 1,2,3 HAVING count(DISTINCT bowler)=1) y
ON x.match_id=y.match_id AND x.innings_no=y.innings_no AND y.over_id=x.over_id+1 AND x.b=y.b;
-- name: bowler_overs_max
SELECT n, count(*) FROM (SELECT match_id, innings_no, bowler, count(DISTINCT over_id) n FROM ball_by_ball GROUP BY 1,2,3) GROUP BY 1;
-- name: striker_eq_nonstriker
SELECT count(*) FROM ball_by_ball WHERE striker = non_striker;
-- name: bowler_is_batter
SELECT count(*) FROM ball_by_ball WHERE bowler IN (striker, non_striker);
-- name: batting_position_rule
-- is striker_batting_position the order in which the striker first appears (as striker or non-striker) in the innings?
WITH app AS (SELECT match_id, innings_no, p, min(k) k FROM (
  SELECT match_id, innings_no, striker p, over_id*100+ball_id k FROM ball_by_ball UNION ALL
  SELECT match_id, innings_no, non_striker, over_id*100+ball_id FROM ball_by_ball) GROUP BY 1,2,3),
rk AS (SELECT match_id, innings_no, p, rank() OVER (PARTITION BY match_id, innings_no ORDER BY k, p) r FROM app),
pos AS (SELECT DISTINCT match_id, innings_no, striker p, striker_batting_position pos FROM ball_by_ball)
SELECT sum(r=pos) eq, sum(r<>pos) ne, count(*) FROM pos JOIN rk USING (match_id, innings_no, p);
-- name: batting_position_constant
SELECT count(*) FROM (SELECT match_id, innings_no, striker FROM ball_by_ball GROUP BY 1,2,3 HAVING count(DISTINCT striker_batting_position)>1);
-- name: batting_position_unique_in_innings
SELECT count(*) FROM (SELECT match_id, innings_no, striker_batting_position FROM ball_by_ball GROUP BY 1,2,3 HAVING count(DISTINCT striker)>1);
-- name: first_ball_positions
SELECT striker_batting_position, count(*) FROM ball_by_ball WHERE over_id=1 AND ball_id=1 GROUP BY 1;
-- name: striker_rotation_rule
-- after a ball, do striker/non-striker swap when total runs off ball is odd? (within over, consecutive balls, no wicket)
WITH b AS (SELECT b.*, coalesce(bs.runs_scored,0) r, coalesce(er.extra_runs,0) e, er.extra_type et, wt.player_out po,
  lead(striker) OVER w nst, lead(non_striker) OVER w nns, lead(over_id) OVER w nov
  FROM ball_by_ball b LEFT JOIN batsman_scored bs USING (match_id,over_id,ball_id,innings_no) LEFT JOIN extra_runs er USING (match_id,over_id,ball_id,innings_no)
  LEFT JOIN wicket_taken wt USING (match_id,over_id,ball_id,innings_no)
  WINDOW w AS (PARTITION BY match_id, innings_no ORDER BY over_id, ball_id))
SELECT CASE WHEN nov=over_id THEN 'same_over' ELSE 'next_over' END k,
  ((r + CASE WHEN et IN ('wides','noballs') THEN e-1 ELSE e END) % 2) odd,
  sum(nst=striker AND nns=non_striker) same, sum(nst=non_striker AND nns=striker) swapped, sum(NOT ((nst=striker AND nns=non_striker) OR (nst=non_striker AND nns=striker))) other
FROM b WHERE po IS NULL AND nst IS NOT NULL GROUP BY 1,2;
-- name: wide_5_runs
SELECT er.extra_runs, bs.runs_scored, count(*) FROM extra_runs er LEFT JOIN batsman_scored bs USING (match_id,over_id,ball_id,innings_no) WHERE extra_type='wides' GROUP BY 1,2;
-- name: wickets_per_innings
SELECT n, count(*) FROM (SELECT b.match_id, b.innings_no, count(w.match_id) n FROM (SELECT DISTINCT match_id, innings_no FROM ball_by_ball) b LEFT JOIN wicket_taken w USING (match_id, innings_no) GROUP BY 1,2) GROUP BY 1;
-- name: player_out_twice
SELECT count(*) FROM (SELECT match_id, innings_no, player_out FROM wicket_taken GROUP BY 1,2,3 HAVING count(*)>1);
-- name: batter_after_out
-- does a dismissed player bat again later in the same innings (retired hurt excepted)?
SELECT w.kind_out, count(DISTINCT w.match_id||'/'||w.innings_no||'/'||w.player_out) FROM wicket_taken w JOIN ball_by_ball b ON b.match_id=w.match_id AND b.innings_no=w.innings_no
 AND (b.over_id*100+b.ball_id) > (w.over_id*100+w.ball_id) AND w.player_out IN (b.striker, b.non_striker) GROUP BY 1;
