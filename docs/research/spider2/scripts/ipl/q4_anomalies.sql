-- name: mixed_matches_all_innings
SELECT match_id, innings_no, team_batting, team_bowling, count(*) balls, count(DISTINCT over_id) overs, min(over_id), max(over_id) FROM ball_by_ball
WHERE match_id IN (392202, 392207, 419119) GROUP BY 1,2,3,4 ORDER BY 1,2,3;
-- name: mixed_matches_meta
SELECT * FROM match WHERE match_id IN (392202, 392207, 419119);
-- name: mixed_overs_shared
-- do the two team_batting groups in innings 2 share (over_id, ball_id) keys? (they cannot: PK) -> show per-over owner
SELECT match_id, over_id, group_concat(DISTINCT team_batting) teams, count(*) FROM ball_by_ball WHERE match_id IN (392202,392207,419119) AND innings_no=2 GROUP BY 1,2 ORDER BY 1,2;
-- name: mixed_pm_teams
SELECT match_id, team_id, count(*) FROM player_match WHERE match_id IN (392202,392207,419119) GROUP BY 1,2;
-- name: mixed_striker_team
-- for the rows labelled with the 'wrong' batting team: which pm team is the striker on?
SELECT b.match_id, b.team_batting, p.team_id striker_pm_team, count(*) FROM ball_by_ball b LEFT JOIN player_match p ON p.match_id=b.match_id AND p.player_id=b.striker
WHERE b.match_id IN (392202,392207,419119) AND b.innings_no=2 GROUP BY 1,2,3;
-- name: m501274_not_in_pm
SELECT b.over_id, b.ball_id, b.innings_no, b.striker, b.non_striker, b.bowler, b.team_batting FROM ball_by_ball b WHERE match_id=501274 AND NOT EXISTS (SELECT 1 FROM player_match p WHERE p.match_id=b.match_id AND p.player_id=b.striker);
-- name: m501274_pm
SELECT team_id, count(*) FROM player_match WHERE match_id=501274 GROUP BY 1;
-- name: side_10_players
SELECT match_id, team_id, count(*) FROM player_match GROUP BY 1,2 HAVING count(*)<>11;
-- name: sides_no_captain_or_2
SELECT match_id, team_id, group_concat(player_id||':'||role) FROM player_match GROUP BY 1,2 HAVING sum(role LIKE 'Captain%')<>1;
-- name: first_ball_children
SELECT 'bs', * FROM (SELECT match_id,over_id,ball_id,innings_no FROM batsman_scored WHERE match_id=335987 AND over_id=1 AND ball_id=1)
UNION ALL SELECT 'wt', match_id,over_id,ball_id,innings_no FROM wicket_taken WHERE match_id=335987 AND over_id=1 AND ball_id=1;
-- name: unused_player
SELECT * FROM player WHERE player_id NOT IN (SELECT player_id FROM player_match);
-- name: player_35_neighbours
SELECT * FROM player WHERE player_id BETWEEN 33 AND 37;
-- name: zero_ball_innings_short
SELECT b.match_id, b.innings_no, max(over_id), m.win_type, m.win_margin FROM ball_by_ball b JOIN match m USING (match_id) GROUP BY 1,2 HAVING max(over_id) < 10;
-- name: legal_7_overs
SELECT b.match_id, b.innings_no, b.over_id, count(*), group_concat(coalesce(er.extra_type,'-')) FROM ball_by_ball b LEFT JOIN extra_runs er USING (match_id,over_id,ball_id,innings_no)
GROUP BY 1,2,3 HAVING sum(coalesce(er.extra_type NOT IN ('wides','noballs'),1))=7;
-- name: legal_0_overs
SELECT b.match_id, b.innings_no, b.over_id, count(*), group_concat(coalesce(er.extra_type,'-')), group_concat(coalesce(wt.kind_out,'-')) FROM ball_by_ball b LEFT JOIN extra_runs er USING (match_id,over_id,ball_id,innings_no)
LEFT JOIN wicket_taken wt USING (match_id,over_id,ball_id,innings_no) GROUP BY 1,2,3 HAVING sum(coalesce(er.extra_type NOT IN ('wides','noballs'),1))=0;
-- name: two_bowler_overs
SELECT match_id, innings_no, over_id, group_concat(bowler) FROM (SELECT * FROM ball_by_ball ORDER BY ball_id) GROUP BY 1,2,3 HAVING count(DISTINCT bowler)>1 LIMIT 5;
-- name: wicket_on_wide_kinds
SELECT w.kind_out, er.extra_type, count(*) FROM wicket_taken w JOIN extra_runs er USING (match_id,over_id,ball_id,innings_no) GROUP BY 1,2;
-- name: chase_consistency
-- does the match winner match the runs totals? innings totals = bs + er
WITH t AS (SELECT b.match_id, b.innings_no, b.team_batting, sum(coalesce(bs.runs_scored,0)+coalesce(er.extra_runs,0)) runs FROM ball_by_ball b
 LEFT JOIN batsman_scored bs USING (match_id,over_id,ball_id,innings_no) LEFT JOIN extra_runs er USING (match_id,over_id,ball_id,innings_no)
 WHERE b.match_id NOT IN (392202,392207,419119) GROUP BY 1,2,3),
w AS (SELECT m.*, t1.runs r1, t1.team_batting b1, t2.runs r2, t2.team_batting b2 FROM match m JOIN t t1 ON t1.match_id=m.match_id AND t1.innings_no=1 JOIN t t2 ON t2.match_id=m.match_id AND t2.innings_no=2)
SELECT win_type, sum(CASE WHEN r1>r2 THEN b1 ELSE b2 END = match_winner) winner_agrees, sum(CASE WHEN r1>r2 THEN b1 ELSE b2 END <> match_winner) disagrees,
 sum(win_type='runs' AND r1-r2=win_margin) margin_eq, sum(win_type='runs' AND r1-r2<>win_margin) margin_ne FROM w GROUP BY 1;
-- name: wickets_margin
WITH wk AS (SELECT match_id, innings_no, count(*) n FROM wicket_taken WHERE kind_out NOT IN ('retired hurt') GROUP BY 1,2)
SELECT sum(10 - coalesce(wk.n,0) = m.win_margin) eq, sum(10 - coalesce(wk.n,0) <> m.win_margin) ne FROM match m LEFT JOIN wk ON wk.match_id=m.match_id AND wk.innings_no=2
WHERE m.win_type='wickets' AND m.match_id NOT IN (392202,392207,419119);
-- name: toss_vs_batting_first
SELECT m.toss_decision, sum(CASE WHEN m.toss_decision='bat' THEN m.toss_winner ELSE (CASE WHEN m.toss_winner=m.team_1 THEN m.team_2 ELSE m.team_1 END) END = b.team_batting) agrees, count(*)
FROM match m JOIN (SELECT match_id, team_batting FROM ball_by_ball WHERE innings_no=1 GROUP BY 1,2) b USING (match_id) GROUP BY 1;
-- name: team1_is_batting_first
SELECT sum(m.team_1 = b.team_batting), count(*) FROM match m JOIN (SELECT match_id, team_batting FROM ball_by_ball WHERE innings_no=1 GROUP BY 1,2) b USING (match_id);
