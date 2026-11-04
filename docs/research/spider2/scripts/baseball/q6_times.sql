-- name: setup_indexes
create index i_player on player(player_id);
-- name: natural_dates_mmdd
select 'home_game.span_last' c, min(substr(span_last,6,5)), max(substr(span_last,6,5)) from home_game
union all select 'home_game.span_first', min(substr(span_first,6,5)), max(substr(span_first,6,5)) from home_game
union all select 'player.debut', min(substr(debut,6,5)), max(substr(debut,6,5)) from player where debut<>''
union all select 'player.final_game', min(substr(final_game,6,5)), max(substr(final_game,6,5)) from player where final_game<>'';
-- name: dates_after_oct31
select sum(substr(span_last,6,5)>'10-31') from home_game;
-- name: birth_vs_events
with b as (select player_id, cast(birth_year as int) by from player where birth_year<>'')
select 'batting' t, count(*), sum(x.year < b.by) before_birth_year, sum(x.year - b.by < 15) age_lt_15 from batting x join b using(player_id)
union all select 'player_college', count(*), sum(x.year < b.by), sum(x.year - b.by < 15) from player_college x join b using(player_id)
union all select 'hall_of_fame', count(*), sum(x.yearid < b.by), null from hall_of_fame x join b using(player_id)
union all select 'debut', count(*), sum(cast(substr(debut,1,4) as int) < b.by), sum(cast(substr(debut,1,4) as int) - b.by < 15) from player x join b using(player_id) where debut<>'';
-- name: birth_after_debut_detail
select player_id, birth_year, birth_month, birth_day, debut from player where debut<>'' and birth_year<>'' and birth_month<>'' and birth_day<>'' and printf('%04d-%02d-%02d',birth_year,birth_month,birth_day) >= debut;
-- name: death_max
select max(printf('%04d-%02d-%02d',death_year,death_month,death_day)), sum(death_year=2016), sum(death_year<>'' and death_month<>'' and death_day<>'' and printf('%04d-%02d-%02d',death_year,death_month,death_day) < final_game) died_before_final_game from player where death_year<>'';
-- name: death_before_birth_detail
select player_id, birth_year, death_year, debut from player where birth_year<>'' and death_year<>'' and death_year<birth_year;
-- name: events_after_death
with d as (select player_id, cast(death_year as int) dy from player where death_year<>'')
select 'batting' t, sum(x.year > d.dy) from batting x join d using(player_id)
union all select 'manager', sum(x.year > d.dy) from manager x join d using(player_id)
union all select 'hall_of_fame (posthumous)', sum(x.yearid > d.dy) from hall_of_fame x join d using(player_id)
union all select 'salary', sum(x.year > d.dy) from salary x join d using(player_id);
-- name: no_birth_year_players
select count(*), sum(debut<>''), min(debut), max(debut) from player where birth_year='';
-- name: postseason_round_codes
select round, count(*), min(year), max(year) from postseason group by 1 order by 3;
