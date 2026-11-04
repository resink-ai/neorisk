-- name: key_uniqueness
select 'all_star(player,year,game_num)' k, count(*) n, (select count(*) from (select distinct player_id,year,game_num from all_star)) d from all_star
union all select 'appearances(year,team,player)', count(*), (select count(*) from (select distinct year,team_id,player_id from appearances)) from appearances
union all select 'batting(player,year,stint)', count(*), (select count(*) from (select distinct player_id,year,stint from batting)) from batting
union all select 'batting_postseason(year,round,player)', count(*), (select count(*) from (select distinct year,round,player_id from batting_postseason)) from batting_postseason
union all select 'batting_postseason(year,round,player,team)', count(*), (select count(*) from (select distinct year,round,player_id,team_id from batting_postseason)) from batting_postseason
union all select 'college(college_id)', count(*), count(distinct college_id) from college
union all select 'fielding(player,year,stint,pos)', count(*), (select count(*) from (select distinct player_id,year,stint,pos from fielding)) from fielding
union all select 'fielding_outfield(player,year,stint)', count(*), (select count(*) from (select distinct player_id,year,stint from fielding_outfield)) from fielding_outfield
union all select 'fielding_postseason(player,year,round,pos)', count(*), (select count(*) from (select distinct player_id,year,round,pos from fielding_postseason)) from fielding_postseason
union all select 'fielding_postseason(player,year,team,round,pos)', count(*), (select count(*) from (select distinct player_id,year,team_id,round,pos from fielding_postseason)) from fielding_postseason
union all select 'hall_of_fame(player,yearid,votedby)', count(*), (select count(*) from (select distinct player_id,yearid,votedby from hall_of_fame)) from hall_of_fame
union all select 'hall_of_fame(player,yearid)', count(*), (select count(*) from (select distinct player_id,yearid from hall_of_fame)) from hall_of_fame
union all select 'home_game(year,team,park)', count(*), (select count(*) from (select distinct year,team_id,park_id from home_game)) from home_game
union all select 'manager(year,team,inseason)', count(*), (select count(*) from (select distinct year,team_id,inseason from manager)) from manager
union all select 'manager_award(player,award,year,league)', count(*), (select count(*) from (select distinct player_id,award_id,year,league_id from manager_award)) from manager_award
union all select 'manager_award_vote(award,year,league,player)', count(*), (select count(*) from (select distinct award_id,year,league_id,player_id from manager_award_vote)) from manager_award_vote
union all select 'manager_half(player,year,team,half)', count(*), (select count(*) from (select distinct player_id,year,team_id,half from manager_half)) from manager_half
union all select 'park(park_id)', count(*), count(distinct park_id) from park
union all select 'pitching(player,year,stint)', count(*), (select count(*) from (select distinct player_id,year,stint from pitching)) from pitching
union all select 'pitching_postseason(player,year,round)', count(*), (select count(*) from (select distinct player_id,year,round from pitching_postseason)) from pitching_postseason
union all select 'player(player_id)', count(*), count(distinct player_id) from player
union all select 'player(lower(player_id))', count(*), count(distinct lower(player_id)) from player
union all select 'player_award(player,award,year,league)', count(*), (select count(*) from (select distinct player_id,award_id,year,league_id from player_award)) from player_award
union all select 'player_award(player,award,year,league,notes)', count(*), (select count(*) from (select distinct player_id,award_id,year,league_id,notes from player_award)) from player_award
union all select 'player_award_vote(award,year,league,player)', count(*), (select count(*) from (select distinct award_id,year,league_id,player_id from player_award_vote)) from player_award_vote
union all select 'player_college(player,college,year)', count(*), (select count(*) from (select distinct player_id,college_id,year from player_college)) from player_college
union all select 'postseason(year,round)', count(*), (select count(*) from (select distinct year,round from postseason)) from postseason
union all select 'salary(year,team,player)', count(*), (select count(*) from (select distinct year,team_id,player_id from salary)) from salary
union all select 'salary(year,player)', count(*), (select count(*) from (select distinct year,player_id from salary)) from salary
union all select 'team(year,team_id)', count(*), (select count(*) from (select distinct year,team_id from team)) from team
union all select 'team_franchise(franchise_id)', count(*), count(distinct franchise_id) from team_franchise
union all select 'team_half(year,team,half)', count(*), (select count(*) from (select distinct year,team_id,half from team_half)) from team_half;
-- name: full_row_duplicates
select 'all_star' t, count(*)-(select count(*) from (select distinct * from all_star)) dup from all_star
union all select 'appearances', count(*)-(select count(*) from (select distinct * from appearances)) from appearances
union all select 'batting', count(*)-(select count(*) from (select distinct * from batting)) from batting
union all select 'fielding', count(*)-(select count(*) from (select distinct * from fielding)) from fielding
union all select 'fielding_postseason', count(*)-(select count(*) from (select distinct * from fielding_postseason)) from fielding_postseason
union all select 'hall_of_fame', count(*)-(select count(*) from (select distinct * from hall_of_fame)) from hall_of_fame
union all select 'player_award', count(*)-(select count(*) from (select distinct * from player_award)) from player_award
union all select 'player_college', count(*)-(select count(*) from (select distinct * from player_college)) from player_college
union all select 'pitching_postseason', count(*)-(select count(*) from (select distinct * from pitching_postseason)) from pitching_postseason
union all select 'batting_postseason', count(*)-(select count(*) from (select distinct * from batting_postseason)) from batting_postseason
union all select 'salary', count(*)-(select count(*) from (select distinct * from salary)) from salary;
-- name: dup_keys_detail_all_star
select player_id, year, game_num, count(*) from all_star group by 1,2,3 having count(*)>1 limit 10;
-- name: dup_keys_detail_fielding_post
select player_id, year, round, pos, count(*), group_concat(team_id) from fielding_postseason group by 1,2,3,4 having count(*)>1 limit 10;
-- name: dup_keys_detail_pitching_post
select player_id, year, round, count(*), group_concat(team_id) from pitching_postseason group by 1,2,3 having count(*)>1 limit 10;
-- name: dup_keys_detail_batting_post
select year, round, player_id, count(*), group_concat(team_id) from batting_postseason group by 1,2,3 having count(*)>1 limit 10;
-- name: dup_keys_detail_hof
select player_id, yearid, votedby, count(*) from hall_of_fame group by 1,2,3 having count(*)>1 limit 10;
-- name: dup_keys_detail_player_award
select player_id, award_id, year, league_id, count(*), group_concat(notes,'|') from player_award group by 1,2,3,4 having count(*)>1 limit 10;
-- name: dup_keys_detail_player_college
select player_id, college_id, year, count(*) from player_college group by 1,2,3 having count(*)>1 limit 10;
-- name: dup_keys_detail_salary
select year, team_id, player_id, count(*), group_concat(salary) from salary group by 1,2,3 having count(*)>1 limit 10;
-- name: dup_keys_detail_postseason
select year, round, count(*) from postseason group by 1,2 having count(*)>1 limit 10;
-- name: dup_keys_detail_manager_award
select player_id, award_id, year, league_id, count(*) from manager_award group by 1,2,3,4 having count(*)>1;
-- name: dup_keys_detail_appearances
select year, team_id, player_id, count(*) from appearances group by 1,2,3 having count(*)>1 limit 10;
-- name: dup_keys_detail_pav
select award_id, year, league_id, player_id, count(*) from player_award_vote group by 1,2,3,4 having count(*)>1 limit 10;
-- name: dup_keys_detail_home_game
select year, team_id, park_id, count(*) from home_game group by 1,2,3 having count(*)>1 limit 10;
