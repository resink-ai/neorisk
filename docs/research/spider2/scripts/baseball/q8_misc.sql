-- name: cabremi_case
select player_id, name_first, name_last from player where lower(player_id)='cabremi01';
-- name: cabremi_vote
select * from player_award_vote where lower(player_id)='cabremi01' order by year;
-- name: orphan_ids_distinct
select count(distinct pid) from (select player_id pid from appearances union all select player_id from salary union all select player_id from all_star union all select player_id from hall_of_fame
 union all select player_id from manager union all select player_id from manager_award union all select player_id from player_award_vote) where pid not in (select player_id from player);
-- name: johnsbi01
select player_id, birth_year, birth_month, birth_day, death_year, debut, final_game, name_first, name_last from player where player_id='johnsbi01';
-- name: leblawa01_era
select player_id, year, ipouts, er, era, baopp from pitching where player_id='leblawa01' and year=2014 or ipouts='';
-- name: notes_ss
select * from player_award where notes='Ss';
-- name: manager_rank_empty
select * from manager where rank='';
-- name: home_game_park_years
select park_id, min(year), max(year) from home_game group by 1 order by 2 limit 3;
-- name: unused_park
select * from park where park_id not in (select park_id from home_game);
