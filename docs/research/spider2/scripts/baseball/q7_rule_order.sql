-- Proposed rules: player.created_at = debut; season aggregates at <year>-11-01; all_star at game date from game_id; hof at <yearid>-01-15.
-- Count rows whose event time would precede the owning player's created_at (debut), for players with a debut.
-- name: setup_indexes
create index i_player on player(player_id);
-- name: events_before_debut
with p as (select player_id, debut from player where debut<>'')
select 'batting' t, count(*) n, sum(printf('%04d-11-01', x.year) < p.debut) before_debut from batting x join p using(player_id)
union all select 'pitching', count(*), sum(printf('%04d-11-01', x.year) < p.debut) from pitching x join p using(player_id)
union all select 'fielding', count(*), sum(printf('%04d-11-01', x.year) < p.debut) from fielding x join p using(player_id)
union all select 'fielding_outfield', count(*), sum(printf('%04d-11-01', x.year) < p.debut) from fielding_outfield x join p using(player_id)
union all select 'appearances', count(*), sum(printf('%04d-11-01', x.year) < p.debut) from appearances x join p using(player_id)
union all select 'salary', count(*), sum(printf('%04d-11-01', x.year) < p.debut) from salary x join p using(player_id)
union all select 'manager', count(*), sum(printf('%04d-11-01', x.year) < p.debut) from manager x join p using(player_id)
union all select 'batting_postseason', count(*), sum(printf('%04d-11-02', x.year) < p.debut) from batting_postseason x join p using(player_id)
union all select 'player_award', count(*), sum(printf('%04d-11-30', x.year) < p.debut) from player_award x join p using(player_id)
union all select 'player_award_vote', count(*), sum(printf('%04d-11-30', x.year) < p.debut) from player_award_vote x join p using(player_id)
union all select 'hall_of_fame', count(*), sum(printf('%04d-01-15', x.yearid) < p.debut) from hall_of_fame x join p using(player_id)
union all select 'all_star (game date)', count(*), sum(x.game_id<>'' and substr(game_id,4,4)||'-'||substr(game_id,8,2)||'-'||substr(game_id,10,2) < p.debut) from all_star x join p using(player_id)
union all select 'player_college (year-06-30)', count(*), sum(printf('%04d-06-30', x.year) < p.debut) from player_college x join p using(player_id);
-- name: events_before_debut_detail
with p as (select player_id, debut from player where debut<>'')
select 'batting' t, x.player_id, x.year, p.debut from batting x join p using(player_id) where printf('%04d-11-01', x.year) < p.debut
union all select 'all_star', x.player_id, x.game_id, p.debut from all_star x join p using(player_id) where x.game_id<>'' and substr(game_id,4,4)||'-'||substr(game_id,8,2)||'-'||substr(game_id,10,2) < p.debut
union all select 'player_award', x.player_id, x.year||' '||x.award_id, p.debut from player_award x join p using(player_id) where printf('%04d-11-30', x.year) < p.debut
union all select 'player_award_vote', x.player_id, x.year||' '||x.award_id, p.debut from player_award_vote x join p using(player_id) where printf('%04d-11-30', x.year) < p.debut
union all select 'salary', x.player_id, x.year, p.debut from salary x join p using(player_id) where printf('%04d-11-01', x.year) < p.debut
union all select 'manager', x.player_id, x.year, p.debut from manager x join p using(player_id) where printf('%04d-11-01', x.year) < p.debut limit 40;
-- name: no_debut_first_event
-- players without debut: first year of any reference (for the created_at rule)
select count(*) n, sum(f is null) never_used, min(f), max(f) from (
 select p.player_id, (select min(y) from (select year y from manager m where m.player_id=p.player_id union all select yearid from hall_of_fame h where h.player_id=p.player_id
   union all select year from appearances a where a.player_id=p.player_id union all select year from batting b where b.player_id=p.player_id
   union all select year from player_award a where a.player_id=p.player_id union all select year from manager_award a where a.player_id=p.player_id
   union all select year from player_college c where c.player_id=p.player_id union all select year from all_star s where s.player_id=p.player_id)) f
 from player p where debut='');
-- name: never_used_players
select p.player_id, name_first, name_last, birth_year from player p where debut='' and player_id not in (select player_id from manager union select player_id from hall_of_fame union select player_id from appearances union select player_id from batting union select player_id from player_award union select player_id from manager_award union select player_id from player_college union select player_id from all_star union select player_id from salary union select player_id from player_award_vote union select player_id from manager_award_vote);
-- name: players_with_event_before_debut
with p as (select player_id, debut from player where debut<>''),
 e as (select player_id, printf('%04d-11-01', year) t from batting union all select player_id, printf('%04d-11-01', year) from pitching
   union all select player_id, printf('%04d-11-01', year) from fielding union all select player_id, printf('%04d-11-01', year) from fielding_outfield
   union all select player_id, printf('%04d-11-01', year) from appearances union all select player_id, printf('%04d-11-01', year) from salary
   union all select player_id, printf('%04d-11-01', year) from manager union all select player_id, printf('%04d-11-02', year) from batting_postseason
   union all select player_id, printf('%04d-11-02', year) from pitching_postseason union all select player_id, printf('%04d-11-02', year) from fielding_postseason
   union all select player_id, printf('%04d-11-30', year) from player_award union all select player_id, printf('%04d-11-30', year) from player_award_vote
   union all select player_id, printf('%04d-11-30', year) from manager_award union all select player_id, printf('%04d-11-30', year) from manager_award_vote
   union all select player_id, printf('%04d-01-15', yearid) from hall_of_fame
   union all select player_id, substr(game_id,4,4)||'-'||substr(game_id,8,2)||'-'||substr(game_id,10,2) from all_star where game_id<>'')
select count(distinct player_id) players, count(*) rows from e join p using(player_id) where e.t < p.debut;
