-- name: matches_per_league_season
select l.name, m.season, count(*) n, count(distinct m.home_team_api_id) teams, max(stage) stages, min(date), max(date)
from Match m join League l on l.id=m.league_id group by 1,2 order by 1,2;
-- name: belgium_2013
select stage, date, count(*) from Match where league_id=1 and season='2013/2014' group by 1,2;
-- name: double_round_robin_check
with s as (select league_id, season, count(*) n, count(distinct home_team_api_id) t from Match group by 1,2)
select sum(n=t*(t-1)) complete, sum(n<>t*(t-1)) incomplete, group_concat(case when n<>t*(t-1) then league_id||' '||season||' '||n||'/'||(t*(t-1)) end, '; ') from s;
-- name: pair_repeat_in_season
select league_id, season, count(*) from (select league_id, season, home_team_api_id, away_team_api_id, count(*) c from Match group by 1,2,3,4 having c>1) group by 1,2;
-- name: team_two_matches_same_day
with x as (select date, home_team_api_id t from Match union all select date, away_team_api_id from Match)
select count(*) from (select date, t, count(*) c from x group by 1,2 having c>1);
-- name: team_two_leagues_same_season
with x as (select season, league_id, home_team_api_id t from Match union select season, league_id, away_team_api_id from Match)
select count(*) from (select season, t, count(distinct league_id) c from x group by 1,2 having c>1);
-- name: teams_change_league
with x as (select home_team_api_id t, league_id from Match union select away_team_api_id, league_id from Match)
select count(*) from (select t, count(distinct league_id) c from x group by 1 having c>1);
-- name: stage_vs_date
select count(*) pairs, sum(d1 > d2) later_stage_earlier_date from (
 select a.date d1, b.date d2 from Match a join Match b on a.league_id=b.league_id and a.season=b.season and a.stage+1=b.stage
 and a.home_team_api_id=b.home_team_api_id);
-- name: stage_date_spread
select max(span) max_days_within_stage, avg(span) from (select league_id, season, stage, julianday(max(date))-julianday(min(date)) span from Match group by 1,2,3);
-- name: weekday_mix
select strftime('%w', date) dow, count(*) from Match group by 1 order by 1;
-- name: month_mix
select substr(date,6,2) m, count(*) from Match group by 1 order by 1;
-- name: matches_per_date
select c, count(*) dates from (select date, count(*) c from Match group by 1) group by 1 order by 1 limit 40;
-- name: result_mix
select case when home_team_goal>away_team_goal then 'H' when home_team_goal<away_team_goal then 'A' else 'D' end r, count(*),
 round(100.0*count(*)/(select count(*) from Match),2) pct from Match group by 1;
-- name: goals_dist
select home_team_goal+away_team_goal g, count(*) from Match group by 1 order by 1;
-- name: goals_mean
select avg(home_team_goal), avg(away_team_goal), max(home_team_goal), max(away_team_goal) from Match;
-- name: lineup_null_pattern
select (home_player_1 is null)+(home_player_2 is null)+(home_player_3 is null)+(home_player_4 is null)+(home_player_5 is null)+(home_player_6 is null)+(home_player_7 is null)+(home_player_8 is null)+(home_player_9 is null)+(home_player_10 is null)+(home_player_11 is null)
 + (away_player_1 is null)+(away_player_2 is null)+(away_player_3 is null)+(away_player_4 is null)+(away_player_5 is null)+(away_player_6 is null)+(away_player_7 is null)+(away_player_8 is null)+(away_player_9 is null)+(away_player_10 is null)+(away_player_11 is null) nulls, count(*)
from Match group by 1 order by 1;
-- name: coords_without_player
select sum(home_player_X1 is not null and home_player_1 is null) x_no_p, sum(home_player_X1 is null and home_player_1 is not null) p_no_x,
 sum(home_player_X1 is null) x_null from Match;
-- name: gk_coords
select home_player_X1, home_player_Y1, count(*) from Match group by 1,2 order by 3 desc limit 6;
-- name: odd_coords
select 'home X1 not 1' k, count(*) from Match where home_player_X1 is not null and home_player_X1<>1
union all select 'away X1 not 1', count(*) from Match where away_player_X1 is not null and away_player_X1<>1
union all select 'X=0 cells', (select count(*) from Match where home_player_X1=0 or home_player_X2=0)
union all select 'Y1 not 1', (select count(*) from Match where home_player_Y1 is not null and home_player_Y1<>1);
-- name: player_in_both_lineups_or_twice
with s(mid, side, pid) as (
 select id,'h',home_player_1 from Match union all select id,'h',home_player_2 from Match union all select id,'h',home_player_3 from Match union all select id,'h',home_player_4 from Match
 union all select id,'h',home_player_5 from Match union all select id,'h',home_player_6 from Match union all select id,'h',home_player_7 from Match union all select id,'h',home_player_8 from Match
 union all select id,'h',home_player_9 from Match union all select id,'h',home_player_10 from Match union all select id,'h',home_player_11 from Match
 union all select id,'a',away_player_1 from Match union all select id,'a',away_player_2 from Match union all select id,'a',away_player_3 from Match union all select id,'a',away_player_4 from Match
 union all select id,'a',away_player_5 from Match union all select id,'a',away_player_6 from Match union all select id,'a',away_player_7 from Match union all select id,'a',away_player_8 from Match
 union all select id,'a',away_player_9 from Match union all select id,'a',away_player_10 from Match union all select id,'a',away_player_11 from Match)
select 'same player twice in one match' k, count(*) from (select mid, pid, count(*) c from s where pid is not null group by 1,2 having c>1)
union all select 'same player on both sides', count(*) from (select mid, pid from s where pid is not null group by 1,2 having count(distinct side)>1);
-- name: player_first_seen
with s(d, pid) as (
 select date,home_player_1 from Match union all select date,home_player_2 from Match union all select date,home_player_3 from Match union all select date,home_player_4 from Match
 union all select date,home_player_5 from Match union all select date,home_player_6 from Match union all select date,home_player_7 from Match union all select date,home_player_8 from Match
 union all select date,home_player_9 from Match union all select date,home_player_10 from Match union all select date,home_player_11 from Match
 union all select date,away_player_1 from Match union all select date,away_player_2 from Match union all select date,away_player_3 from Match union all select date,away_player_4 from Match
 union all select date,away_player_5 from Match union all select date,away_player_6 from Match union all select date,away_player_7 from Match union all select date,away_player_8 from Match
 union all select date,away_player_9 from Match union all select date,away_player_10 from Match union all select date,away_player_11 from Match),
fm as (select pid, min(d) first_match from s where pid is not null group by 1),
fa as (select player_api_id pid, min(date) first_attr from Player_Attributes group by 1)
select count(*) players, sum(first_attr <= first_match) attr_first, sum(first_attr > first_match) match_first,
  sum(first_attr='2007-02-22 00:00:00') first_attr_2007_02_22, min(first_attr), max(first_attr), max(first_match) from fm join fa using(pid);
-- name: player_first_attr_dates
select first_attr, count(*) from (select player_api_id, min(date) first_attr from Player_Attributes group by 1) group by 1 order by 2 desc limit 8;
-- name: birthday_vs_first_attr
select min((julianday(fa)-julianday(birthday))/365.25) min_age_years, max((julianday(fa)-julianday(birthday))/365.25) from Player p join (select player_api_id, min(date) fa from Player_Attributes group by 1) using(player_api_id);
-- name: team_first_match
select min(fm), max(fm), sum(fm='2008-07-18 00:00:00' or fm < '2008-09-01') in_first_window, count(*) from (
 select t.team_api_id, (select min(date) from Match m where m.home_team_api_id=t.team_api_id or m.away_team_api_id=t.team_api_id) fm from Team t);
-- name: team_attr_before_first_match
select count(*) teams_with_attr, sum(fa < fm) attr_before_match from (
 select t.team_api_id, (select min(date) from Team_Attributes a where a.team_api_id=t.team_api_id) fa,
  (select min(date) from Match m where m.home_team_api_id=t.team_api_id or m.away_team_api_id=t.team_api_id) fm from Team t) where fa is not null;
-- name: snapshot_dates_global
select 'Match' t, min(date), max(date) from Match union all select 'PA', min(date), max(date) from Player_Attributes
union all select 'TA', min(date), max(date) from Team_Attributes union all select 'birthday', min(birthday), max(birthday) from Player;
-- name: pa_dates_top
select date, count(*) from Player_Attributes group by 1 order by 2 desc limit 15;
-- name: pa_distinct_dates
select count(distinct date) from Player_Attributes;
-- name: pa_change_between_snapshots
-- How often a snapshot repeats the previous one for the same player (all 38 rated columns equal)
with o as (select a.*, lag(overall_rating) over w por, lag(potential) over w ppot, lag(crossing) over w pcr, lag(finishing) over w pfi, lag(gk_reflexes) over w pgk, lag(date) over w pd
 from Player_Attributes a window w as (partition by player_api_id order by date, id))
select count(*) with_prev, sum(overall_rating is por and potential is ppot and crossing is pcr and finishing is pfi and gk_reflexes is pgk) same_5_cols,
 sum(date=pd) same_date from o where pd is not null;
-- name: pa_gap_days
with o as (select date, lag(date) over (partition by player_api_id order by date, id) pd from Player_Attributes)
select case when g=0 then '0' when g<=31 then '1-31' when g<=92 then '32-92' when g<=183 then '93-183' when g<=366 then '184-366' else '>366' end b, count(*)
from (select julianday(date)-julianday(pd) g from o where pd is not null) group by 1 order by min(g);
-- name: ta_class_thresholds
select 'buildUpPlaySpeed' c, buildUpPlaySpeedClass k, min(buildUpPlaySpeed), max(buildUpPlaySpeed), count(*) from Team_Attributes group by 2
union all select 'buildUpPlayDribbling', buildUpPlayDribblingClass, min(buildUpPlayDribbling), max(buildUpPlayDribbling), count(*) from Team_Attributes group by 2
union all select 'buildUpPlayPassing', buildUpPlayPassingClass, min(buildUpPlayPassing), max(buildUpPlayPassing), count(*) from Team_Attributes group by 2
union all select 'chanceCreationPassing', chanceCreationPassingClass, min(chanceCreationPassing), max(chanceCreationPassing), count(*) from Team_Attributes group by 2
union all select 'chanceCreationCrossing', chanceCreationCrossingClass, min(chanceCreationCrossing), max(chanceCreationCrossing), count(*) from Team_Attributes group by 2
union all select 'chanceCreationShooting', chanceCreationShootingClass, min(chanceCreationShooting), max(chanceCreationShooting), count(*) from Team_Attributes group by 2
union all select 'defencePressure', defencePressureClass, min(defencePressure), max(defencePressure), count(*) from Team_Attributes group by 2
union all select 'defenceAggression', defenceAggressionClass, min(defenceAggression), max(defenceAggression), count(*) from Team_Attributes group by 2
union all select 'defenceTeamWidth', defenceTeamWidthClass, min(defenceTeamWidth), max(defenceTeamWidth), count(*) from Team_Attributes group by 2
union all select 'positioning/line classes', buildUpPlayPositioningClass||'/'||chanceCreationPositioningClass||'/'||defenceDefenderLineClass, null, null, count(*) from Team_Attributes group by 2;
-- name: ta_class_rule_exact
-- class = Low (<=33) / Mid (34..66) / High (>=67) per column; Dribbling NULL -> 'Normal'?
select 'speed' c, sum(buildUpPlaySpeedClass <> case when buildUpPlaySpeed<=33 then 'Slow' when buildUpPlaySpeed<=66 then 'Balanced' else 'Fast' end) bad from Team_Attributes
union all select 'dribbling (non-null)', sum(buildUpPlayDribblingClass <> case when buildUpPlayDribbling<=33 then 'Little' when buildUpPlayDribbling<=66 then 'Normal' else 'Lots' end) from Team_Attributes where buildUpPlayDribbling is not null
union all select 'dribbling (null) class values', count(distinct buildUpPlayDribblingClass) from Team_Attributes where buildUpPlayDribbling is null
union all select 'bu passing', sum(buildUpPlayPassingClass <> case when buildUpPlayPassing<=33 then 'Short' when buildUpPlayPassing<=66 then 'Mixed' else 'Long' end) from Team_Attributes
union all select 'cc passing', sum(chanceCreationPassingClass <> case when chanceCreationPassing<=33 then 'Safe' when chanceCreationPassing<=66 then 'Normal' else 'Risky' end) from Team_Attributes
union all select 'cc crossing', sum(chanceCreationCrossingClass <> case when chanceCreationCrossing<=33 then 'Little' when chanceCreationCrossing<=66 then 'Normal' else 'Lots' end) from Team_Attributes
union all select 'cc shooting', sum(chanceCreationShootingClass <> case when chanceCreationShooting<=33 then 'Little' when chanceCreationShooting<=66 then 'Normal' else 'Lots' end) from Team_Attributes
union all select 'def pressure', sum(defencePressureClass <> case when defencePressure<=33 then 'Deep' when defencePressure<=66 then 'Medium' else 'High' end) from Team_Attributes
union all select 'def aggression', sum(defenceAggressionClass <> case when defenceAggression<=33 then 'Contain' when defenceAggression<=66 then 'Press' else 'Double' end) from Team_Attributes
union all select 'def width', sum(defenceTeamWidthClass <> case when defenceTeamWidth<=33 then 'Narrow' when defenceTeamWidth<=66 then 'Normal' else 'Wide' end) from Team_Attributes;
-- name: pa_rating_vs_potential
select sum(potential < overall_rating) potential_below_rating, count(overall_rating) from Player_Attributes;
-- name: match_api_id_vs_date
select count(*) pairs, sum(a.match_api_id < b.match_api_id) from Match a join Match b on b.id=a.id+1 and a.league_id=b.league_id and a.season=b.season and a.date<b.date;
-- name: ta_dribbling_null_class
select buildUpPlayDribblingClass, count(*) from Team_Attributes where buildUpPlayDribbling is null group by 1;
-- name: dup_player_in_match_sample
select id, league_id, season, date, home_team_api_id, away_team_api_id from Match where home_player_1 in (away_player_1,away_player_2,away_player_3,away_player_4,away_player_5,away_player_6,away_player_7,away_player_8,away_player_9,away_player_10,away_player_11) or home_player_2 in (away_player_1,away_player_2,away_player_3,away_player_4,away_player_5,away_player_6,away_player_7,away_player_8,away_player_9,away_player_10,away_player_11) limit 5;
