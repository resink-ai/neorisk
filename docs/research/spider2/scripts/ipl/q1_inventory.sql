-- name: row_counts
SELECT 'player' t, count(*) FROM player UNION ALL SELECT 'team', count(*) FROM team UNION ALL SELECT 'match', count(*) FROM match
UNION ALL SELECT 'player_match', count(*) FROM player_match UNION ALL SELECT 'ball_by_ball', count(*) FROM ball_by_ball
UNION ALL SELECT 'batsman_scored', count(*) FROM batsman_scored UNION ALL SELECT 'wicket_taken', count(*) FROM wicket_taken
UNION ALL SELECT 'extra_runs', count(*) FROM extra_runs;
-- name: team_rows
SELECT * FROM team ORDER BY team_id;
-- name: team_ids_used_not_in_team
SELECT x, count(*) FROM (SELECT team_1 x FROM match UNION ALL SELECT team_2 FROM match UNION ALL SELECT team_id FROM player_match
 UNION ALL SELECT team_batting FROM ball_by_ball) WHERE x NOT IN (SELECT team_id FROM team) GROUP BY x;
-- name: player_id_gaps
WITH RECURSIVE s(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM s WHERE i<469) SELECT i FROM s WHERE i NOT IN (SELECT player_id FROM player);
-- name: player_ids_used_not_in_player
SELECT 'pm' src, count(*) FROM player_match WHERE player_id NOT IN (SELECT player_id FROM player)
UNION ALL SELECT 'striker', count(*) FROM ball_by_ball WHERE striker NOT IN (SELECT player_id FROM player)
UNION ALL SELECT 'non_striker', count(*) FROM ball_by_ball WHERE non_striker NOT IN (SELECT player_id FROM player)
UNION ALL SELECT 'bowler', count(*) FROM ball_by_ball WHERE bowler NOT IN (SELECT player_id FROM player)
UNION ALL SELECT 'player_out', count(*) FROM wicket_taken WHERE player_out NOT IN (SELECT player_id FROM player)
UNION ALL SELECT 'motm', count(*) FROM match WHERE man_of_the_match NOT IN (SELECT player_id FROM player);
-- name: match_ids_not_in_match
SELECT 'bbb' src, match_id, count(*) FROM ball_by_ball WHERE match_id NOT IN (SELECT match_id FROM match) GROUP BY match_id
UNION ALL SELECT 'bs', match_id, count(*) FROM batsman_scored WHERE match_id NOT IN (SELECT match_id FROM match) GROUP BY match_id
UNION ALL SELECT 'wt', match_id, count(*) FROM wicket_taken WHERE match_id NOT IN (SELECT match_id FROM match) GROUP BY match_id
UNION ALL SELECT 'er', match_id, count(*) FROM extra_runs WHERE match_id NOT IN (SELECT match_id FROM match) GROUP BY match_id
UNION ALL SELECT 'pm', match_id, count(*) FROM player_match WHERE match_id NOT IN (SELECT match_id FROM match) GROUP BY match_id;
-- name: orphan_match_detail
SELECT innings_no, team_batting, team_bowling, count(*) balls, min(over_id), max(over_id) FROM ball_by_ball
WHERE match_id NOT IN (SELECT match_id FROM match) GROUP BY 1,2,3;
-- name: matches_per_season
SELECT season_id, count(*), min(match_date), max(match_date) FROM match GROUP BY 1;
-- name: cats_match
SELECT 'toss_decision' c, toss_decision v, count(*) FROM match GROUP BY 2 UNION ALL
SELECT 'win_type', win_type, count(*) FROM match GROUP BY 2 UNION ALL SELECT 'outcome_type', outcome_type, count(*) FROM match GROUP BY 2;
-- name: cats_player
SELECT 'batting_hand' c, batting_hand v, count(*) FROM player GROUP BY 2 UNION ALL
SELECT 'bowling_skill', bowling_skill, count(*) FROM player GROUP BY 2 UNION ALL SELECT 'country', country_name, count(*) FROM player GROUP BY 2;
-- name: cats_role
SELECT role, count(*) FROM player_match GROUP BY 1;
-- name: cats_kind_out
SELECT kind_out, count(*) FROM wicket_taken GROUP BY 1 ORDER BY 2 DESC;
-- name: cats_extra
SELECT extra_type, extra_runs, count(*) FROM extra_runs GROUP BY 1,2 ORDER BY 1,2;
-- name: runs_dist
SELECT runs_scored, count(*) FROM batsman_scored GROUP BY 1;
-- name: date_formats
SELECT 'match_date' c, count(*) n, sum(match_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]') ok, sum(date(match_date)=match_date) valid FROM match
UNION ALL SELECT 'dob', count(*), sum(dob GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'), sum(date(dob)=dob) FROM player;
-- name: rowid_order
SELECT 'match' t, sum(o) FROM (SELECT match_id < lag(match_id) OVER (ORDER BY rowid) o FROM match)
UNION ALL SELECT 'player', sum(o) FROM (SELECT player_id < lag(player_id) OVER (ORDER BY rowid) o FROM player)
UNION ALL SELECT 'bbb_by_key', sum(o) FROM (SELECT (match_id,over_id,ball_id,innings_no) < (lag(match_id) OVER w, lag(over_id) OVER w, lag(ball_id) OVER w, lag(innings_no) OVER w) o FROM ball_by_ball WINDOW w AS (ORDER BY rowid))
UNION ALL SELECT 'match_id_vs_date', sum(o) FROM (SELECT match_date < lag(match_date) OVER (ORDER BY match_id) o FROM match);
-- name: match_id_date_inversions
SELECT * FROM (SELECT match_id, match_date, lag(match_id) OVER (ORDER BY match_id) pid, lag(match_date) OVER (ORDER BY match_id) pd, season_id FROM match) WHERE match_date < pd;
-- name: matches_per_day
SELECT n, count(*) days FROM (SELECT match_date, count(*) n FROM match GROUP BY 1) GROUP BY 1;
-- name: country_typo
SELECT country_name, count(*) FROM player WHERE country_name LIKE 'Zimb%' GROUP BY 1;
-- name: dup_player_names
SELECT player_name, count(*) FROM player GROUP BY 1 HAVING count(*)>1;
