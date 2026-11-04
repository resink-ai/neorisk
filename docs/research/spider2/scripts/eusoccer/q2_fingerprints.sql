-- name: country_id_is_first_match_id
select c.id, c.name, (select min(id) from Match m where m.country_id=c.id) first_match_id,
  (select count(*) from Match m where m.country_id=c.id) matches from Country c order by c.id;
-- name: team_id_vs_first_match_id
with f as (select t.id, t.team_api_id,
  (select min(id) from Match m where m.home_team_api_id=t.team_api_id or m.away_team_api_id=t.team_api_id) fm
 from Team t)
select sum(id=fm) equal, sum(id<>fm) differ, count(*) n from f;
-- name: team_id_vs_first_match_id_differ_sample
with f as (select t.id, t.team_api_id, t.team_long_name,
  (select min(id) from Match m where m.home_team_api_id=t.team_api_id or m.away_team_api_id=t.team_api_id) fm,
  (select min(id) from Match m where m.home_team_api_id=t.team_api_id) fhm,
  (select min(id) from Match m where m.away_team_api_id=t.team_api_id) fam
 from Team t)
select * from f where id<>fm limit 20;
-- name: player_id_gaps
select id+1 missing_from from Player p where not exists (select 1 from Player q where q.id=p.id+1) and id<11075;
-- name: pa_duplicate_player_date
select count(*) groups, sum(c) rows, sum(nulls) rows_with_null_rating from (
 select player_api_id, date, count(*) c, sum(overall_rating is null) nulls from Player_Attributes group by 1,2 having c>1);
-- name: pa_null_rating_rows
select count(*) n, sum(potential is null), sum(preferred_foot is null), sum(crossing is null), sum(gk_reflexes is null),
 sum(exists (select 1 from Player_Attributes b where b.player_api_id=a.player_api_id and b.date=a.date and b.id<>a.id)) has_twin_same_date
from Player_Attributes a where overall_rating is null;
-- name: pa_dup_sample
select a.id, a.player_api_id, a.date, a.overall_rating, a.crossing, a.volleys from Player_Attributes a
where (a.player_api_id, a.date) in (select player_api_id, date from Player_Attributes group by 1,2 having count(*)>1) order by a.player_api_id, a.date, a.id limit 12;
-- name: pa_null_rating_players
select count(distinct player_api_id) players, sum(only_null) players_all_null from (
 select player_api_id, min(overall_rating is null) only_null from Player_Attributes where player_api_id in (select player_api_id from Player_Attributes where overall_rating is null) group by 1);
-- name: pa_null_dates
select date, count(*) from Player_Attributes where overall_rating is null group by 1 order by 2 desc limit 10;
-- name: pa_partial_null
select 'volleys..null but rating not' k, count(*) from Player_Attributes where volleys is null and overall_rating is not null
union all select 'attacking_work_rate null but rating not', count(*) from Player_Attributes where attacking_work_rate is null and overall_rating is not null
union all select 'the 5 late stats null set: same rows', count(*) from Player_Attributes where (volleys is null)+(curve is null)+(agility is null)+(balance is null)+(jumping is null)+(vision is null)+(sliding_tackle is null) not in (0,7);
-- name: pa_partial_null_dates
select min(date), max(date), count(*) from Player_Attributes where volleys is null and overall_rating is not null;
-- name: pa_fifa_mismatch
select pa.player_api_id, p.player_fifa_api_id player_fifa, pa.player_fifa_api_id pa_fifa, count(*) rows,
  (select count(*) from Player x where x.player_fifa_api_id=pa.player_fifa_api_id) fifa_in_player
from Player_Attributes pa join Player p using(player_api_id) where p.player_fifa_api_id<>pa.player_fifa_api_id group by 1,2,3 order by rows desc limit 20;
-- name: pa_fifa_mismatch_summary
select count(distinct pa.player_api_id) players, count(*) rows, sum(pa.player_fifa_api_id in (select player_fifa_api_id from Player)) rows_fifa_owned_by_other_player
from Player_Attributes pa join Player p using(player_api_id) where p.player_fifa_api_id<>pa.player_fifa_api_id;
-- name: pa_player_with_two_blocks
select player_api_id, count(*) from (select player_api_id, id - row_number() over (partition by player_api_id order by id) grp from Player_Attributes) group by player_api_id having count(distinct grp)>1;
-- name: pa_date_order_breaks_sample
select * from (select id, player_api_id pid, date d, lag(date) over (order by id) pd, lag(player_api_id) over (order by id) ppid from Player_Attributes) where pid=ppid and d>pd limit 10;
-- name: ta_dup
select * from Team_Attributes where (team_api_id, date) in (select team_api_id, date from Team_Attributes group by 1,2 having count(*)>1);
-- name: ta_dates
select date, count(*) from Team_Attributes group by 1 order by 1;
-- name: ta_per_team
select c, count(*) teams from (select team_api_id, count(*) c from Team_Attributes group by 1) group by 1 order by 1;
-- name: ta_dribbling_null_by_date
select date, count(*), sum(buildUpPlayDribbling is null) from Team_Attributes group by 1 order by 1;
-- name: pa_rows_per_player
select c, count(*) players from (select player_api_id, count(*) c from Player_Attributes group by 1) group by 1 order by 1;
-- name: pa_year_counts
select substr(date,1,4) y, count(*), count(distinct player_api_id) from Player_Attributes group by 1 order by 1;
-- name: date_formats
select 'Match.date' k, count(*), sum(date glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] 00:00:00') midnight from Match
union all select 'PA.date', count(*), sum(date glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] 00:00:00') from Player_Attributes
union all select 'TA.date', count(*), sum(date glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] 00:00:00') from Team_Attributes
union all select 'Player.birthday', count(*), sum(birthday glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] 00:00:00') from Player
union all select 'valid dates (date() roundtrip) Match', count(*), sum(date(date)||' 00:00:00'=date) from Match
union all select 'valid PA', count(*), sum(date(date)||' 00:00:00'=date) from Player_Attributes
union all select 'valid birthday', count(*), sum(date(birthday)||' 00:00:00'=birthday) from Player;
-- name: work_rate_values
select 'attacking' k, attacking_work_rate v, count(*) from Player_Attributes group by 2
union all select 'defensive', defensive_work_rate, count(*) from Player_Attributes group by 2 order by 1, 3 desc;
-- name: preferred_foot
select preferred_foot, count(*) from Player_Attributes group by 1;
-- name: height_values
select height, count(*), printf('%.17g', height) full17, cast(height as text) txt, round(height/2.54,6) inches from Player group by 1 order by 1;
-- name: weight_range
select min(weight), max(weight), count(distinct weight) from Player;
-- name: player_name_ws
select count(*) from Player where player_name like '%  %' or player_name<>trim(player_name);
-- name: team_name_nonascii
select count(*) from Team where team_long_name <> cast(cast(team_long_name as blob) as text) or length(cast(team_long_name as blob))<>length(team_long_name);
