-- name: pk_unique
SELECT 'bbb' t, count(*) - (SELECT count(*) FROM (SELECT DISTINCT match_id,over_id,ball_id,innings_no FROM ball_by_ball)) dup FROM ball_by_ball
UNION ALL SELECT 'bs', count(*) - (SELECT count(*) FROM (SELECT DISTINCT match_id,over_id,ball_id,innings_no FROM batsman_scored)) FROM batsman_scored
UNION ALL SELECT 'wt', count(*) - (SELECT count(*) FROM (SELECT DISTINCT match_id,over_id,ball_id,innings_no FROM wicket_taken)) FROM wicket_taken
UNION ALL SELECT 'er', count(*) - (SELECT count(*) FROM (SELECT DISTINCT match_id,over_id,ball_id,innings_no FROM extra_runs)) FROM extra_runs
UNION ALL SELECT 'pm', count(*) - (SELECT count(*) FROM (SELECT DISTINCT match_id,player_id FROM player_match)) FROM player_match;
-- name: child_without_ball
SELECT 'bs' t, count(*) FROM batsman_scored s WHERE NOT EXISTS (SELECT 1 FROM ball_by_ball b WHERE b.match_id=s.match_id AND b.over_id=s.over_id AND b.ball_id=s.ball_id AND b.innings_no=s.innings_no)
UNION ALL SELECT 'wt', count(*) FROM wicket_taken s WHERE NOT EXISTS (SELECT 1 FROM ball_by_ball b WHERE b.match_id=s.match_id AND b.over_id=s.over_id AND b.ball_id=s.ball_id AND b.innings_no=s.innings_no)
UNION ALL SELECT 'er', count(*) FROM extra_runs s WHERE NOT EXISTS (SELECT 1 FROM ball_by_ball b WHERE b.match_id=s.match_id AND b.over_id=s.over_id AND b.ball_id=s.ball_id AND b.innings_no=s.innings_no);
-- name: ball_coverage
SELECT (bs.match_id IS NOT NULL) has_bs, (er.match_id IS NOT NULL) has_er, (wt.match_id IS NOT NULL) has_wt, count(*)
FROM ball_by_ball b
LEFT JOIN batsman_scored bs USING (match_id,over_id,ball_id,innings_no)
LEFT JOIN extra_runs er USING (match_id,over_id,ball_id,innings_no)
LEFT JOIN wicket_taken wt USING (match_id,over_id,ball_id,innings_no) GROUP BY 1,2,3 ORDER BY 1,2,3;
-- name: no_bs_extra_types
SELECT er.extra_type, (wt.match_id IS NOT NULL) has_wt, count(*) FROM ball_by_ball b
LEFT JOIN batsman_scored bs USING (match_id,over_id,ball_id,innings_no)
LEFT JOIN extra_runs er USING (match_id,over_id,ball_id,innings_no)
LEFT JOIN wicket_taken wt USING (match_id,over_id,ball_id,innings_no) WHERE bs.match_id IS NULL GROUP BY 1,2;
-- name: bs_by_extra_type
SELECT er.extra_type, bs.runs_scored, count(*) FROM batsman_scored bs JOIN extra_runs er USING (match_id,over_id,ball_id,innings_no) GROUP BY 1,2 ORDER BY 1,2;
-- name: matches_missing_children
SELECT 'no_bbb' k, count(*) FROM match WHERE match_id NOT IN (SELECT match_id FROM ball_by_ball)
UNION ALL SELECT 'no_pm', count(*) FROM match WHERE match_id NOT IN (SELECT match_id FROM player_match)
UNION ALL SELECT 'no_wt', count(*) FROM match WHERE match_id NOT IN (SELECT match_id FROM wicket_taken);
-- name: players_per_match_team
SELECT n, count(*) FROM (SELECT match_id, team_id, count(*) n FROM player_match GROUP BY 1,2) GROUP BY 1;
-- name: pm_team_in_match
SELECT count(*) bad FROM player_match pm JOIN match m USING (match_id) WHERE pm.team_id NOT IN (m.team_1, m.team_2);
-- name: teams_per_match_pm
SELECT n, count(*) FROM (SELECT match_id, count(DISTINCT team_id) n FROM player_match GROUP BY 1) GROUP BY 1;
-- name: captains_keepers_per_side
SELECT caps, keeps, count(*) FROM (SELECT match_id, team_id, sum(role LIKE 'Captain%') caps, sum(role LIKE '%Keeper') keeps FROM player_match GROUP BY 1,2) GROUP BY 1,2;
-- name: ball_players_in_pm
SELECT 'striker' r, count(*) FROM ball_by_ball b WHERE NOT EXISTS (SELECT 1 FROM player_match p WHERE p.match_id=b.match_id AND p.player_id=b.striker AND p.team_id=b.team_batting)
UNION ALL SELECT 'non_striker', count(*) FROM ball_by_ball b WHERE NOT EXISTS (SELECT 1 FROM player_match p WHERE p.match_id=b.match_id AND p.player_id=b.non_striker AND p.team_id=b.team_batting)
UNION ALL SELECT 'bowler', count(*) FROM ball_by_ball b WHERE NOT EXISTS (SELECT 1 FROM player_match p WHERE p.match_id=b.match_id AND p.player_id=b.bowler AND p.team_id=b.team_bowling)
UNION ALL SELECT 'player_out', count(*) FROM wicket_taken w JOIN ball_by_ball b USING (match_id,over_id,ball_id,innings_no) WHERE w.player_out NOT IN (b.striker, b.non_striker);
-- name: player_out_not_on_crease_detail
SELECT w.kind_out, count(*), sum(EXISTS (SELECT 1 FROM player_match p WHERE p.match_id=w.match_id AND p.player_id=w.player_out AND p.team_id=b.team_batting)) in_batting_xi
FROM wicket_taken w JOIN ball_by_ball b USING (match_id,over_id,ball_id,innings_no) WHERE w.player_out NOT IN (b.striker, b.non_striker) GROUP BY 1;
-- name: bbb_teams_vs_match
SELECT count(*) bad FROM ball_by_ball b JOIN match m USING (match_id) WHERE b.team_batting NOT IN (m.team_1,m.team_2) OR b.team_bowling NOT IN (m.team_1,m.team_2) OR b.team_batting=b.team_bowling;
-- name: innings_batting_team_constant
SELECT count(*) FROM (SELECT match_id, innings_no FROM ball_by_ball GROUP BY 1,2 HAVING count(DISTINCT team_batting)>1 OR count(DISTINCT team_bowling)>1);
-- name: innings_per_match
SELECT n, count(*) FROM (SELECT match_id, count(DISTINCT innings_no) n FROM ball_by_ball GROUP BY 1) GROUP BY 1;
-- name: winner_in_match
SELECT sum(match_winner NOT IN (team_1,team_2)) bad_winner, sum(toss_winner NOT IN (team_1,team_2)) bad_toss, sum(team_1=team_2) same FROM match;
-- name: motm_in_match
SELECT count(*) motm_not_in_pm FROM match m WHERE NOT EXISTS (SELECT 1 FROM player_match p WHERE p.match_id=m.match_id AND p.player_id=m.man_of_the_match);
-- name: player_35_usage
SELECT team_id, role, count(*), min(match_id), max(match_id) FROM player_match WHERE player_id=35 GROUP BY 1,2;
-- name: player_35_motm
SELECT match_id, match_date FROM match WHERE man_of_the_match=35;
-- name: unused_players
SELECT count(*) FROM player WHERE player_id NOT IN (SELECT player_id FROM player_match);
-- name: neighbours_419136
SELECT match_id, match_date, season_id, team_1, team_2, venue FROM match WHERE match_id BETWEEN 419133 AND 419139;
-- name: team1_usage
SELECT season_id, count(*) FROM match WHERE 1 IN (team_1,team_2) GROUP BY 1;
