-- name: result_vs_score
-- matches (excluding the 3 mislabelled innings) where the scorecard does not give the recorded winner or runs margin
WITH t AS (SELECT k.match_id, k.innings_no, sum(coalesce(s.runs_scored,0)+coalesce(e.extra_runs,0)) runs, max(k.over_id) mo FROM
 (SELECT match_id, innings_no, over_id, ball_id FROM ball_by_ball UNION SELECT match_id, innings_no, over_id, ball_id FROM extra_runs) k
 LEFT JOIN batsman_scored s USING (match_id,over_id,ball_id,innings_no) LEFT JOIN extra_runs e USING (match_id,over_id,ball_id,innings_no) GROUP BY 1,2),
bt AS (SELECT match_id, innings_no, min(team_batting) tb FROM ball_by_ball GROUP BY 1,2)
SELECT m.match_id, m.match_date, m.win_type, m.win_margin, t1.runs r1, t2.runs r2, t1.mo o1, t2.mo o2, b1.tb bat1, m.match_winner,
 CASE WHEN t1.runs>t2.runs THEN b1.tb ELSE b2.tb END score_winner
FROM match m JOIN t t1 ON t1.match_id=m.match_id AND t1.innings_no=1 JOIN t t2 ON t2.match_id=m.match_id AND t2.innings_no=2
JOIN bt b1 ON b1.match_id=m.match_id AND b1.innings_no=1 JOIN bt b2 ON b2.match_id=m.match_id AND b2.innings_no=2
WHERE m.match_id NOT IN (392202,392207,419119) AND (CASE WHEN t1.runs>t2.runs THEN b1.tb ELSE b2.tb END <> m.match_winner OR (m.win_type='runs' AND t1.runs-t2.runs<>m.win_margin))
ORDER BY 1;
