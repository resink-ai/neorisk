-- name: m419136_totals
SELECT b.innings_no, b.team_batting, sum(coalesce(s.runs_scored,0)) bat, sum(coalesce(e.extra_runs,0)) extras, count(w.match_id) wkts FROM ball_by_ball b
LEFT JOIN batsman_scored s USING (match_id,over_id,ball_id,innings_no) LEFT JOIN extra_runs e USING (match_id,over_id,ball_id,innings_no) LEFT JOIN wicket_taken w USING (match_id,over_id,ball_id,innings_no)
WHERE b.match_id=419136 GROUP BY 1,2;
-- name: team1_home_venues
SELECT venue, count(*) FROM match WHERE 1 IN (team_1, team_2) GROUP BY 1 ORDER BY 2 DESC LIMIT 3;
-- name: deliveries_per_innings_quantiles
WITH d AS (SELECT match_id, innings_no, count(*) n FROM ball_by_ball GROUP BY 1,2), o AS (SELECT n, row_number() OVER (ORDER BY n) r, count(*) OVER () c FROM d)
SELECT min(n), max(CASE WHEN r<=c*0.1 THEN n END) p10, max(CASE WHEN r<=c*0.5 THEN n END) p50, max(CASE WHEN r<=c*0.9 THEN n END) p90, max(n), avg(n) FROM o;
-- name: innings_totals_quantiles
WITH t AS (SELECT b.match_id, b.innings_no, sum(coalesce(s.runs_scored,0)+coalesce(e.extra_runs,0)) runs FROM ball_by_ball b LEFT JOIN batsman_scored s USING (match_id,over_id,ball_id,innings_no) LEFT JOIN extra_runs e USING (match_id,over_id,ball_id,innings_no) GROUP BY 1,2),
o AS (SELECT innings_no, runs, row_number() OVER (PARTITION BY innings_no ORDER BY runs) r, count(*) OVER (PARTITION BY innings_no) c FROM t)
SELECT innings_no, min(runs), max(CASE WHEN r<=c*0.1 THEN runs END) p10, max(CASE WHEN r<=c*0.5 THEN runs END) p50, max(CASE WHEN r<=c*0.9 THEN runs END) p90, max(runs), round(avg(runs),1) FROM o GROUP BY 1;
-- name: per_delivery_rates
SELECT count(*) deliveries, (SELECT count(*) FROM batsman_scored) bs_rows, (SELECT count(*) FROM extra_runs) extras, (SELECT count(*) FROM wicket_taken) wickets,
 round(1.0*(SELECT count(*) FROM extra_runs)/count(*),4) extra_rate, round(1.0*(SELECT count(*) FROM wicket_taken)/count(*),4) wicket_rate,
 round(1.0*(SELECT sum(runs_scored) FROM batsman_scored)/count(*),4) bat_runs_per_delivery FROM ball_by_ball;
-- name: runs_per_over_dist
WITH o AS (SELECT b.match_id, b.innings_no, b.over_id, sum(coalesce(s.runs_scored,0)+coalesce(e.extra_runs,0)) runs FROM ball_by_ball b LEFT JOIN batsman_scored s USING (match_id,over_id,ball_id,innings_no) LEFT JOIN extra_runs e USING (match_id,over_id,ball_id,innings_no) GROUP BY 1,2,3)
SELECT CASE WHEN runs<5 THEN '0-4' WHEN runs<10 THEN '5-9' WHEN runs<15 THEN '10-14' WHEN runs<20 THEN '15-19' ELSE '20+' END band, count(*) FROM o GROUP BY 1;
-- name: run_rate_by_over
SELECT b.over_id, round(1.0*sum(coalesce(s.runs_scored,0)+coalesce(e.extra_runs,0))/count(DISTINCT b.match_id||'/'||b.innings_no),2) runs_per_over, round(1.0*count(w.match_id)/count(DISTINCT b.match_id||'/'||b.innings_no),3) wkts_per_over
FROM ball_by_ball b LEFT JOIN batsman_scored s USING (match_id,over_id,ball_id,innings_no) LEFT JOIN extra_runs e USING (match_id,over_id,ball_id,innings_no) LEFT JOIN wicket_taken w USING (match_id,over_id,ball_id,innings_no) GROUP BY 1;
-- name: toss_decision_by_season
SELECT season_id, sum(toss_decision='field') field, sum(toss_decision='bat') bat FROM match GROUP BY 1;
-- name: toss_winner_wins
SELECT sum(toss_winner=match_winner) toss_win_match, count(*) FROM match;
-- name: bat_first_wins
SELECT win_type, count(*) FROM match GROUP BY 1;
-- name: margin_quantiles
WITH o AS (SELECT win_type, win_margin m, row_number() OVER (PARTITION BY win_type ORDER BY win_margin) r, count(*) OVER (PARTITION BY win_type) c FROM match)
SELECT win_type, min(m), max(CASE WHEN r<=c*0.25 THEN m END) p25, max(CASE WHEN r<=c*0.5 THEN m END) p50, max(CASE WHEN r<=c*0.75 THEN m END) p75, max(m) FROM o GROUP BY 1;
-- name: days_between_matches
WITH d AS (SELECT DISTINCT season_id, match_date FROM match), g AS (SELECT season_id, julianday(match_date) - julianday(lag(match_date) OVER (PARTITION BY season_id ORDER BY match_date)) gap FROM d)
SELECT gap, count(*) FROM g WHERE gap IS NOT NULL GROUP BY 1;
-- name: weekday_mix
SELECT strftime('%w', match_date) dow, count(*) FROM match GROUP BY 1;
-- name: venue_top
SELECT venue, count(*) FROM match GROUP BY 1 ORDER BY 2 DESC LIMIT 8;
-- name: appearances_per_player
SELECT CASE WHEN n=1 THEN '1' WHEN n<=10 THEN '2-10' WHEN n<=50 THEN '11-50' WHEN n<=100 THEN '51-100' ELSE '101+' END b, count(*) FROM (SELECT player_id, count(*) n FROM player_match GROUP BY 1) GROUP BY 1;
-- name: max_appearances
SELECT p.player_name, count(*) FROM player_match pm JOIN player p USING (player_id) GROUP BY 1 ORDER BY 2 DESC LIMIT 3;
-- name: teams_per_player
SELECT n, count(*) FROM (SELECT player_id, count(DISTINCT team_id) n FROM player_match GROUP BY 1) GROUP BY 1;
-- name: team_change_within_season
SELECT count(*) FROM (SELECT pm.player_id, m.season_id FROM player_match pm JOIN match m USING (match_id) GROUP BY 1,2 HAVING count(DISTINCT pm.team_id)>1);
-- name: dismissal_mix_by_innings
SELECT innings_no, kind_out, count(*) FROM wicket_taken GROUP BY 1,2 ORDER BY 1,3 DESC;
-- name: all_out_or_20
WITH i AS (SELECT b.match_id, b.innings_no, max(b.over_id) mo, (SELECT count(*) FROM wicket_taken w WHERE w.match_id=b.match_id AND w.innings_no=b.innings_no) wk FROM ball_by_ball b GROUP BY 1,2)
SELECT innings_no, sum(wk=10) all_out, sum(mo=20 AND wk<10) to_20_overs, sum(mo<20 AND wk<10) ended_early, count(*) FROM i GROUP BY 1;
-- name: player_created_rule
-- first appearance date per player; how many players appear first in each season
SELECT s, count(*) FROM (SELECT pm.player_id, min(m.season_id) s FROM player_match pm JOIN match m USING (match_id) GROUP BY 1) GROUP BY 1;
-- name: first_appearance_in_bbb_before_pm
-- any player who appears in ball_by_ball in a match earlier than his first player_match row?
SELECT count(*) FROM (SELECT p, min(d) d FROM (SELECT b.striker p, m.match_date d FROM ball_by_ball b JOIN match m USING (match_id) UNION ALL SELECT b.bowler, m.match_date FROM ball_by_ball b JOIN match m USING (match_id)
 UNION ALL SELECT b.non_striker, m.match_date FROM ball_by_ball b JOIN match m USING (match_id)) GROUP BY 1) x
JOIN (SELECT pm.player_id p, min(m.match_date) d FROM player_match pm JOIN match m USING (match_id) GROUP BY 1) y USING (p) WHERE x.d < y.d;
-- name: dob_range_age_at_first
SELECT min(age), max(age), round(avg(age),1) FROM (SELECT (julianday(min(m.match_date)) - julianday(p.dob))/365.25 age FROM player p JOIN player_match pm USING (player_id) JOIN match m USING (match_id) GROUP BY p.player_id);
