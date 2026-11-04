-- name: setup_indexes
create index i_team on team(year, team_id);
create index i_player on player(player_id);
create index i_bat on batting(player_id, year);
create index i_app on appearances(player_id, year);
-- name: appearances_player_orphans
select player_id, year, team_id, count(*) from appearances where player_id not in (select player_id from player) group by 1,2,3;
-- name: allstar_player_orphan
select * from all_star where player_id not in (select player_id from player);
-- name: manager_award_orphan
select * from manager_award where player_id not in (select player_id from player);
-- name: appearances_team_orphans
select year, team_id, league_id, count(*) from appearances s where not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id) group by 1,2,3 order by 4 desc limit 20;
-- name: appearances_team_orphans_summary
select count(distinct year||team_id), min(year), max(year) from appearances s where not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id);
-- name: appearances_league_only_mismatch
select s.year, s.team_id, s.league_id, x.league_id from appearances s join team x on x.year=s.year and x.team_id=s.team_id where x.league_id<>s.league_id;
-- name: postseason_team_orphans
select year, round, team_id_winner, team_id_loser from postseason s where not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id_winner) or not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id_loser);
-- name: college_orphans
select college_id, count(*) from player_college where college_id not in (select college_id from college) group by 1;
-- name: no_debut_but_appears
select p.player_id, p.name_first, p.name_last, p.debut, p.final_game, (select group_concat(year||team_id) from appearances a where a.player_id=p.player_id) from player p where debut='' and player_id in (select player_id from appearances);
-- name: no_debut_where_used
select sum(player_id in (select player_id from hall_of_fame)) hof, sum(player_id in (select player_id from manager)) mgr,
 sum(player_id in (select player_id from batting)) bat, sum(player_id in (select player_id from player_award)) award, sum(player_id in (select player_id from salary)) sal,
 sum(player_id not in (select player_id from hall_of_fame) and player_id not in (select player_id from manager) and player_id not in (select player_id from appearances)) none_of_these,
 sum(final_game='') no_final from player where debut='';
-- name: date_formats
select 'debut' c, count(*), sum(debut glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'), sum(debut<>'' and date(debut) is null), sum(debut<>'' and date(debut)<>debut) from player
union all select 'final_game', count(*), sum(final_game glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'), sum(final_game<>'' and date(final_game) is null), sum(final_game<>'' and date(final_game)<>final_game) from player
union all select 'span_first', count(*), sum(span_first glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'), sum(date(span_first) is null), sum(date(span_first)<>span_first) from home_game
union all select 'span_last', count(*), sum(span_last glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'), sum(date(span_last) is null), sum(date(span_last)<>span_last) from home_game;
-- name: debut_vs_stats
select count(*) players_with_debut_and_batting,
 sum(cast(substr(debut,1,4) as int) = (select min(year) from batting b where b.player_id=p.player_id)) debut_year_eq_first_bat_year,
 sum(cast(substr(debut,1,4) as int) > (select min(year) from batting b where b.player_id=p.player_id)) debut_after_first_bat,
 sum(cast(substr(final_game,1,4) as int) = (select max(year) from batting b where b.player_id=p.player_id)) final_eq_last_bat_year,
 sum(cast(substr(final_game,1,4) as int) < (select max(year) from batting b where b.player_id=p.player_id)) final_before_last_bat,
 sum(final_game < debut) final_before_debut
from player p where debut<>'' and player_id in (select player_id from batting);
-- name: debut_mismatch_examples
select player_id, debut, final_game, (select min(year) from batting b where b.player_id=p.player_id) first_bat, (select max(year) from batting b where b.player_id=p.player_id) last_bat from player p where debut<>'' and player_id in (select player_id from batting) and (cast(substr(debut,1,4) as int) <> (select min(year) from batting b where b.player_id=p.player_id) or cast(substr(final_game,1,4) as int) <> (select max(year) from batting b where b.player_id=p.player_id)) limit 15;
-- name: snapshot_dates
select max(debut), max(final_game), sum(final_game='2015-10-04'), sum(final_game>='2015-09-01'), max(death_year), (select max(yearid) from hall_of_fame), (select max(span_last) from home_game) from player where final_game<>'';
-- name: birth_death_partial
select sum(birth_year<>'' and birth_month<>'' and birth_day<>'') full_birth, sum(birth_year<>'' and (birth_month='' or birth_day='')) partial_birth, sum(birth_year='') no_birth_year,
 sum(death_year<>'' and death_month<>'' and death_day<>'') full_death, sum(death_year<>'' and (death_month='' or death_day='')) partial_death,
 sum(death_year='' and (death_country<>'' or death_state<>'' or death_city<>'')) place_without_year,
 sum(birth_year<>'' and death_year<>'' and death_year<birth_year) death_before_birth,
 sum(birth_year<>'' and birth_month<>'' and birth_day<>'' and date(printf('%04d-%02d-%02d',birth_year,birth_month,birth_day)) is null) invalid_birth_date,
 sum(death_year<>'' and death_month<>'' and death_day<>'' and date(printf('%04d-%02d-%02d',death_year,death_month,death_day)) is null) invalid_death_date
from player;
-- name: allstar_gameid_date
select count(*) n, sum(game_id='') no_game_id,
 sum(game_id<>'' and cast(substr(game_id,4,4) as int)=year) gid_year_eq,
 sum(game_id<>'' and date(substr(game_id,4,4)||'-'||substr(game_id,8,2)||'-'||substr(game_id,10,2)) is not null) gid_valid_date,
 sum(game_id<>'' and cast(substr(game_id,12,1) as int)=game_num) gid_suffix_eq_game_num,
 min(substr(game_id,8,4)) min_mmdd, max(substr(game_id,8,4)) max_mmdd
from all_star;
-- name: allstar_no_gameid
select year, game_num, count(*) from all_star where game_id='' group by 1,2;
-- name: allstar_gameids_per_year
select year, count(distinct game_id) g, group_concat(distinct game_num) from all_star group by 1 having count(distinct game_id)>1;
-- name: odd_text_in_numeric
select 'pitching_postseason.era' c, era, count(*) from pitching_postseason where typeof(era)='text' and era<>'' group by 2
union all select 'pitching_postseason.baopp nonnumeric', baopp, count(*) from pitching_postseason where baopp<>'' and cast(baopp as real)||''<>baopp and baopp glob '*[^0-9.]*' group by 2;
-- name: ps_baopp_forms
select case when baopp='' then 'empty' when baopp glob '.[0-9]*' then 'leading dot' when baopp glob '0.[0-9]*' then '0.x' when baopp glob '[0-9]' then 'integer' else baopp end f, count(*), min(baopp), max(baopp) from pitching_postseason group by 1;
-- name: real_points_won
select award_id, year, league_id, player_id, points_won, votes_first from player_award_vote where typeof(points_won)='real' or typeof(votes_first)='real';
-- name: award_id_case
select 'manager_award_vote' t, award_id, count(*) from manager_award_vote group by 2
union all select 'manager_award', award_id, count(*) from manager_award group by 2
union all select 'player_award_vote', award_id, count(*) from player_award_vote group by 2;
-- name: player_award_notes
select notes, count(*) from player_award group by 1 order by 2 desc;
-- name: league_ids
select 'team' t, league_id, count(*) from team group by 2 union all select 'batting', league_id, count(*) from batting group by 2;
-- name: empty_league_years
select 'batting' t, min(year), max(year), count(*) from batting where league_id='' union all select 'team', min(year), max(year), count(*) from team where league_id='';
-- name: salary_values
select count(*), sum(salary=0), min(salary), max(salary), sum(salary%1000=0), sum(salary%10000=0) from salary;
-- name: home_game_spans
select count(*), sum(span_last<span_first) last_before_first, sum(cast(substr(span_first,1,4) as int)<>year) first_year_ne, sum(cast(substr(span_last,1,4) as int)<>year) last_year_ne, sum(openings>games) openings_gt_games, sum(attendance=0) zero_att from home_game;
-- name: team_ids_multi_franchise
select team_id, group_concat(distinct franchise_id), group_concat(distinct league_id) from team group by 1 having count(distinct franchise_id)>1 or count(distinct league_id)>1;
-- name: hof_categories
select votedby, category, inducted, count(*), sum(ballots=''), sum(needed=''), sum(votes='') from hall_of_fame group by 1,2,3 order by 4 desc;
-- name: team_flags
select div_win, wc_win, lg_win, ws_win, count(*) from team group by 1,2,3,4 order by 5 desc limit 15;
-- name: park_country
select country, count(*), sum(state='') from park group by 1;
-- name: year_coverage
select 'appearances' t, min(year), max(year) from appearances union all select 'salary', min(year), max(year) from salary
union all select 'home_game', min(year), max(year) from home_game union all select 'player_college', min(year), max(year) from player_college
union all select 'fielding_outfield', min(year), max(year) from fielding_outfield union all select 'team_half', min(year), max(year) from team_half
union all select 'manager_award_vote', min(year), max(year) from manager_award_vote union all select 'player_award_vote', min(year), max(year) from player_award_vote;
-- name: player_college_vs_debut
select count(*), sum(p.debut<>'' and pc.year > cast(substr(p.debut,1,4) as int)) college_after_debut_year, sum(p.debut='') no_debut from player_college pc join player p using(player_id);
