-- name: local007_variant_b_debut_nonempty
select avg(round(abs(cast(substr(final_game,1,4) as int)-cast(substr(debut,1,4) as int)),2)
         + round(abs(cast(substr(final_game,6,2) as int)-cast(substr(debut,6,2) as int))/12.0,2)
         + round(abs(cast(substr(final_game,9,2) as int)-cast(substr(debut,9,2) as int))/365.0,2)) v, count(*) n
from player where debut<>'' and final_game<>'';
-- name: local007_variant_all_rows
select avg(round(abs(cast(substr(final_game,1,4) as int)-cast(substr(debut,1,4) as int)),2)
         + round(abs(cast(substr(final_game,6,2) as int)-cast(substr(debut,6,2) as int))/12.0,2)
         + round(abs(cast(substr(final_game,9,2) as int)-cast(substr(debut,9,2) as int))/365.0,2)) v, count(*) n
from player;
-- name: local007_variant_julian
select avg(round(abs(julianday(final_game)-julianday(debut))/365.25,2)) v1, round(avg((julianday(final_game)-julianday(debut))/365.0),2) v2, count(*) n from player where debut<>'';
-- name: local007_variant_a_rounded
select round(avg(round(abs(cast(substr(final_game,1,4) as int)-cast(substr(debut,1,4) as int)),2)
         + round(abs(cast(substr(final_game,6,2) as int)-cast(substr(debut,6,2) as int))/12.0,2)
         + round(abs(cast(substr(final_game,9,2) as int)-cast(substr(debut,9,2) as int))/365.0,2)),2) v
from player where debut<>'';
-- name: local007_variant_age_style
-- full years, then remaining months, then remaining days (borrowing), as an "age" difference
with d as (select cast(substr(debut,1,4) as int) y1, cast(substr(debut,6,2) as int) m1, cast(substr(debut,9,2) as int) d1,
                  cast(substr(final_game,1,4) as int) y2, cast(substr(final_game,6,2) as int) m2, cast(substr(final_game,9,2) as int) d2 from player where debut<>''),
 e as (select y2-y1 - (case when m2*100+d2 < m1*100+d1 then 1 else 0 end) yy,
              ((m2 - m1 - (case when d2<d1 then 1 else 0 end)) + 12) % 12 mm,
              case when d2>=d1 then d2-d1 else d2-d1+30 end dd from d)
select avg(round(abs(yy),2)+round(abs(mm)/12.0,2)+round(abs(dd)/365.0,2)) v, round(avg(round(abs(yy),2)+round(abs(mm)/12.0,2)+round(abs(dd)/365.0,2)),2) v2 from e;
-- name: local008_gold_sql
WITH player_stats AS (
    SELECT b.player_id, p.name_given AS player_name, SUM(b.g) AS games_played, SUM(b.r) AS runs, SUM(b.h) AS hits, SUM(b.hr) AS home_runs
    FROM player p JOIN batting b ON p.player_id = b.player_id GROUP BY b.player_id, p.name_given)
SELECT 'Games Played' AS Category, player_name AS Player_Name, games_played AS Batting_Table_Topper FROM player_stats WHERE games_played = (SELECT MAX(games_played) FROM player_stats)
UNION ALL SELECT 'Runs', player_name, runs FROM player_stats WHERE runs = (SELECT MAX(runs) FROM player_stats)
UNION ALL SELECT 'Hits', player_name, hits FROM player_stats WHERE hits = (SELECT MAX(hits) FROM player_stats)
UNION ALL SELECT 'Home Runs', player_name, home_runs FROM player_stats WHERE home_runs = (SELECT MAX(home_runs) FROM player_stats);
-- name: local008_sum_types
-- SUM over a column holding '' : SQLite counts '' as 0; with '' mapped to NULL the sums are unchanged
select typeof(sum(r)), sum(r), sum(nullif(r,'')), total(r) from batting;
-- name: local007_weighted_by_join
with s as (select player_id, round(abs(cast(substr(final_game,1,4) as int)-cast(substr(debut,1,4) as int)),2)
         + round(abs(cast(substr(final_game,6,2) as int)-cast(substr(debut,6,2) as int))/12.0,2)
         + round(abs(cast(substr(final_game,9,2) as int)-cast(substr(debut,9,2) as int))/365.0,2) span from player where debut<>'')
select 'join batting' w, avg(span), count(*) from s join batting using(player_id)
union all select 'join appearances', avg(span), count(*) from s join appearances using(player_id)
union all select 'join fielding', avg(span), count(*) from s join fielding using(player_id)
union all select 'join pitching', avg(span), count(*) from s join pitching using(player_id)
union all select 'distinct span values', avg(distinct span), count(distinct span) from s;
