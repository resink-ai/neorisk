-- name: setup_indexes
create index i_team on team(year, team_id);
create index i_player on player(player_id);
create index i_app on appearances(player_id, year, team_id);
create index i_bat on batting(player_id, year, team_id);
create index i_fld on fielding(player_id, year, stint, pos);
create index i_mgr on manager(player_id, year, team_id, inseason);
create index i_pa on player_award(player_id, award_id, year, league_id);
create index i_ps on postseason(year, round);
-- name: player_fk_orphans
select 'all_star' t, count(*) n, sum(player_id not in (select player_id from player)) orphan from all_star
union all select 'appearances', count(*), sum(player_id not in (select player_id from player)) from appearances
union all select 'batting', count(*), sum(player_id not in (select player_id from player)) from batting
union all select 'batting_postseason', count(*), sum(player_id not in (select player_id from player)) from batting_postseason
union all select 'fielding', count(*), sum(player_id not in (select player_id from player)) from fielding
union all select 'fielding_outfield', count(*), sum(player_id not in (select player_id from player)) from fielding_outfield
union all select 'fielding_postseason', count(*), sum(player_id not in (select player_id from player)) from fielding_postseason
union all select 'hall_of_fame', count(*), sum(player_id not in (select player_id from player)) from hall_of_fame
union all select 'manager', count(*), sum(player_id not in (select player_id from player)) from manager
union all select 'manager_award', count(*), sum(player_id not in (select player_id from player)) from manager_award
union all select 'manager_award_vote', count(*), sum(player_id not in (select player_id from player)) from manager_award_vote
union all select 'manager_half', count(*), sum(player_id not in (select player_id from player)) from manager_half
union all select 'pitching', count(*), sum(player_id not in (select player_id from player)) from pitching
union all select 'pitching_postseason', count(*), sum(player_id not in (select player_id from player)) from pitching_postseason
union all select 'player_award', count(*), sum(player_id not in (select player_id from player)) from player_award
union all select 'player_award_vote', count(*), sum(player_id not in (select player_id from player)) from player_award_vote
union all select 'player_college', count(*), sum(player_id not in (select player_id from player)) from player_college
union all select 'salary', count(*), sum(player_id not in (select player_id from player)) from salary;
-- name: player_orphan_detail
select 'hall_of_fame' t, player_id, count(*) from hall_of_fame where player_id not in (select player_id from player) group by 2
union all select 'player_award_vote', player_id, count(*) from player_award_vote where player_id not in (select player_id from player) group by 2
union all select 'salary', player_id, count(*) from salary where player_id not in (select player_id from player) group by 2
union all select 'manager', player_id, count(*) from manager where player_id not in (select player_id from player) group by 2;
-- name: team_year_fk_orphans
select 'appearances' t, count(*) n, sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id)) orphan, sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id and x.league_id=s.league_id)) orphan_with_league from appearances s
union all select 'batting', count(*), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id)), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id and x.league_id=s.league_id)) from batting s
union all select 'pitching', count(*), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id)), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id and x.league_id=s.league_id)) from pitching s
union all select 'fielding', count(*), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id)), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id and x.league_id=s.league_id)) from fielding s
union all select 'manager', count(*), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id)), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id and x.league_id=s.league_id)) from manager s
union all select 'salary', count(*), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id)), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id and x.league_id=s.league_id)) from salary s
union all select 'all_star', count(*), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id)), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id and x.league_id=s.league_id)) from all_star s
union all select 'home_game', count(*), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id)), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id and x.league_id=s.league_id)) from home_game s
union all select 'team_half', count(*), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id)), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id and x.league_id=s.league_id)) from team_half s
union all select 'manager_half', count(*), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id)), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id and x.league_id=s.league_id)) from manager_half s
union all select 'batting_postseason', count(*), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id)), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id and x.league_id=s.league_id)) from batting_postseason s
union all select 'pitching_postseason', count(*), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id)), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id and x.league_id=s.league_id)) from pitching_postseason s
union all select 'fielding_postseason', count(*), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id)), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id and x.league_id=s.league_id)) from fielding_postseason s
union all select 'postseason.winner', count(*), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id_winner)), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id_winner and x.league_id=s.league_id_winner)) from postseason s
union all select 'postseason.loser', count(*), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id_loser)), sum(not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id_loser and x.league_id=s.league_id_loser)) from postseason s;
-- name: team_year_orphan_detail
select 'all_star' t, year, team_id, league_id, count(*) from all_star s where not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id) group by 2,3,4
union all select 'salary', year, team_id, league_id, count(*) from salary s where not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id) group by 2,3,4
union all select 'home_game', year, team_id, league_id, count(*) from home_game s where not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id) group by 2,3,4
union all select 'team_half', year, team_id, league_id, count(*) from team_half s where not exists(select 1 from team x where x.year=s.year and x.team_id=s.team_id) group by 2,3,4;
-- name: league_mismatch_detail
select 'salary' t, s.year, s.team_id, s.league_id, x.league_id team_league, count(*) from salary s join team x on x.year=s.year and x.team_id=s.team_id where x.league_id<>s.league_id group by 2,3,4,5
union all select 'all_star', s.year, s.team_id, s.league_id, x.league_id, count(*) from all_star s join team x on x.year=s.year and x.team_id=s.team_id where x.league_id<>s.league_id group by 2,3,4,5
union all select 'batting', s.year, s.team_id, s.league_id, x.league_id, count(*) from batting s join team x on x.year=s.year and x.team_id=s.team_id where x.league_id<>s.league_id group by 2,3,4,5
union all select 'home_game', s.year, s.team_id, s.league_id, x.league_id, count(*) from home_game s join team x on x.year=s.year and x.team_id=s.team_id where x.league_id<>s.league_id group by 2,3,4,5 limit 30;
-- name: other_fk
select 'team.franchise_id->team_franchise' fk, count(*) n, sum(franchise_id not in (select franchise_id from team_franchise)) orphan from team
union all select 'home_game.park_id->park', count(*), sum(park_id not in (select park_id from park)) from home_game
union all select 'player_college.college_id->college', count(*), sum(college_id not in (select college_id from college)) from player_college
union all select 'team.park->park.park_name (nonempty)', sum(park<>''), sum(park<>'' and park not in (select park_name from park) and park not in (select park_alias from park where park_alias<>'')) from team
union all select 'fielding_outfield->fielding(player,year,stint,OF)', count(*), sum(not exists(select 1 from fielding f where f.player_id=o.player_id and f.year=o.year and f.stint=o.stint and f.pos='OF')) from fielding_outfield o
union all select 'fielding->appearances(player,year,team)', count(*), sum(not exists(select 1 from appearances a where a.player_id=f.player_id and a.year=f.year and a.team_id=f.team_id)) from fielding f
union all select 'batting->appearances(player,year,team)', count(*), sum(not exists(select 1 from appearances a where a.player_id=f.player_id and a.year=f.year and a.team_id=f.team_id)) from batting f
union all select 'appearances->batting(player,year,team)', count(*), sum(not exists(select 1 from batting b where b.player_id=a.player_id and b.year=a.year and b.team_id=a.team_id)) from appearances a
union all select 'pitching->appearances', count(*), sum(not exists(select 1 from appearances a where a.player_id=f.player_id and a.year=f.year and a.team_id=f.team_id)) from pitching f
union all select 'manager_half->manager(player,year,team,inseason)', count(*), sum(not exists(select 1 from manager m where m.player_id=h.player_id and m.year=h.year and m.team_id=h.team_id and m.inseason=h.inseason)) from manager_half h
union all select 'team_half->team', count(*), sum(not exists(select 1 from team t where t.year=h.year and t.team_id=h.team_id)) from team_half h
union all select 'postseason lines->postseason(year,round,team)', (select count(*) from batting_postseason), (select count(*) from batting_postseason b where not exists(select 1 from postseason p where p.year=b.year and p.round=b.round and b.team_id in (p.team_id_winner,p.team_id_loser))) 
union all select 'player_award_vote->player_award (same player,award,year,league)', count(*), sum(not exists(select 1 from player_award a where a.player_id=v.player_id and a.award_id=v.award_id and a.year=v.year and a.league_id=v.league_id)) from player_award_vote v;
-- name: team_franchise_used
select count(*) n, sum(franchise_id in (select franchise_id from team)) used from team_franchise;
-- name: park_used
select count(*) n, sum(park_id in (select park_id from home_game)) used from park;
-- name: college_used
select count(*) n, sum(college_id in (select college_id from player_college)) used from college;
-- name: team_id_functional
select 'team_id -> franchise_id' f, count(*) from (select team_id from team group by 1 having count(distinct franchise_id)>1)
union all select 'team_id -> league_id', count(*) from (select team_id from team group by 1 having count(distinct league_id)>1)
union all select 'team_id -> name', count(*) from (select team_id from team group by 1 having count(distinct name)>1)
union all select 'team_id -> team_id_br', count(*) from (select team_id from team group by 1 having count(distinct team_id_br)>1)
union all select 'team_id = team_id_lahman45 rows', sum(team_id=team_id_lahman45) from team
union all select 'team_id = team_id_retro rows', sum(team_id=team_id_retro) from team
union all select 'distinct team_id', count(distinct team_id) from team
union all select 'distinct franchise_id', count(distinct franchise_id) from team;
-- name: player_usage
select count(*) n,
 sum(player_id in (select player_id from appearances)) in_appearances,
 sum(player_id in (select player_id from batting)) in_batting,
 sum(player_id in (select player_id from manager)) in_manager,
 sum(player_id not in (select player_id from appearances) and player_id not in (select player_id from manager)) neither,
 sum(debut='') no_debut,
 sum(debut='' and player_id in (select player_id from appearances)) no_debut_but_appears,
 sum(debut='' and player_id in (select player_id from hall_of_fame)) no_debut_in_hof,
 sum(debut='' and player_id in (select player_id from manager)) no_debut_in_manager
from player;
-- name: rowid_order
select 'batting by (year? player?)' t,
 (select count(*) from batting a join batting b on b.rowid=a.rowid+1 where (b.player_id,b.year,b.stint) < (a.player_id,a.year,a.stint)) player_key_breaks,
 (select count(*) from batting a join batting b on b.rowid=a.rowid+1 where b.year < a.year) year_breaks
union all select 'player', (select count(*) from player a join player b on b.rowid=a.rowid+1 where b.player_id<a.player_id), null
union all select 'appearances', (select count(*) from appearances a join appearances b on b.rowid=a.rowid+1 where (b.year,b.team_id,b.player_id)<(a.year,a.team_id,a.player_id)), (select count(*) from appearances a join appearances b on b.rowid=a.rowid+1 where b.year<a.year)
union all select 'fielding', (select count(*) from fielding a join fielding b on b.rowid=a.rowid+1 where (b.player_id,b.year,b.stint)<(a.player_id,a.year,a.stint)), (select count(*) from fielding a join fielding b on b.rowid=a.rowid+1 where b.year<a.year)
union all select 'pitching', (select count(*) from pitching a join pitching b on b.rowid=a.rowid+1 where (b.player_id,b.year,b.stint)<(a.player_id,a.year,a.stint)), (select count(*) from pitching a join pitching b on b.rowid=a.rowid+1 where b.year<a.year)
union all select 'salary', (select count(*) from salary a join salary b on b.rowid=a.rowid+1 where (b.year,b.team_id,b.player_id)<(a.year,a.team_id,a.player_id)), (select count(*) from salary a join salary b on b.rowid=a.rowid+1 where b.year<a.year)
union all select 'team', (select count(*) from team a join team b on b.rowid=a.rowid+1 where (b.year,b.league_id,b.team_id)<(a.year,a.league_id,a.team_id)), (select count(*) from team a join team b on b.rowid=a.rowid+1 where b.year<a.year);
