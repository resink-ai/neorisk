-- name: row_counts
select 'Country' t, count(*) n from Country union all select 'League', count(*) from League
union all select 'Team', count(*) from Team union all select 'Team_Attributes', count(*) from Team_Attributes
union all select 'Player', count(*) from Player union all select 'Player_Attributes', count(*) from Player_Attributes
union all select 'Match', count(*) from Match union all select 'sqlite_sequence', count(*) from sqlite_sequence;
-- name: sqlite_sequence_vs_max_id
select s.name, s.seq,
  case s.name when 'Country' then (select max(id) from Country) when 'League' then (select max(id) from League)
   when 'Team' then (select max(id) from Team) when 'Team_Attributes' then (select max(id) from Team_Attributes)
   when 'Player' then (select max(id) from Player) when 'Player_Attributes' then (select max(id) from Player_Attributes)
   when 'Match' then (select max(id) from Match) end as max_id
from sqlite_sequence s order by s.name;
-- name: country_league
select c.id cid, c.name country, l.id lid, l.country_id, l.name league from Country c left join League l on l.country_id=c.id order by c.id;
-- name: id_gaps
select 'Player' t, count(*) n, min(id), max(id), max(id)-min(id)+1-count(*) gaps from Player
union all select 'Team', count(*), min(id), max(id), max(id)-min(id)+1-count(*) from Team
union all select 'Match', count(*), min(id), max(id), max(id)-min(id)+1-count(*) from Match
union all select 'Player_Attributes', count(*), min(id), max(id), max(id)-min(id)+1-count(*) from Player_Attributes
union all select 'Team_Attributes', count(*), min(id), max(id), max(id)-min(id)+1-count(*) from Team_Attributes;
-- name: team_id_sample
select id, team_api_id, team_fifa_api_id, team_long_name, team_short_name from Team order by id limit 12;
-- name: team_id_jumps
select id, lag(id) over (order by id) prev from Team order by id;
-- name: key_uniqueness
select 'Player.player_api_id' k, count(*) n, count(distinct player_api_id) d from Player
union all select 'Player.player_fifa_api_id', count(*), count(distinct player_fifa_api_id) from Player
union all select 'Player.player_name', count(*), count(distinct player_name) from Player
union all select 'Team.team_api_id', count(*), count(distinct team_api_id) from Team
union all select 'Team.team_fifa_api_id (non-null)', count(team_fifa_api_id), count(distinct team_fifa_api_id) from Team
union all select 'Team.team_long_name', count(*), count(distinct team_long_name) from Team
union all select 'Team.team_short_name', count(*), count(distinct team_short_name) from Team
union all select 'Match.match_api_id', count(*), count(distinct match_api_id) from Match
union all select 'Match(league,season,stage,home)', count(*), count(distinct league_id||'|'||season||'|'||stage||'|'||home_team_api_id) from Match
union all select 'Match(home,away,season)', count(*), count(distinct home_team_api_id||'|'||away_team_api_id||'|'||season) from Match
union all select 'PA(player_api_id,date)', count(*), count(distinct player_api_id||'|'||date) from Player_Attributes
union all select 'PA(player_fifa_api_id,date)', count(*), count(distinct player_fifa_api_id||'|'||date) from Player_Attributes
union all select 'TA(team_api_id,date)', count(*), count(distinct team_api_id||'|'||date) from Team_Attributes;
-- name: team_fifa_dupes
select team_fifa_api_id, count(*), group_concat(team_api_id||':'||team_long_name, ' ; ') from Team where team_fifa_api_id is not null group by 1 having count(*)>1;
-- name: team_fifa_null
select id, team_api_id, team_long_name, team_short_name, (select count(*) from Match m where m.home_team_api_id=t.team_api_id or m.away_team_api_id=t.team_api_id) matches from Team t where team_fifa_api_id is null;
-- name: team_longname_dupes
select team_long_name, count(*), group_concat(team_api_id||'/'||ifnull(team_fifa_api_id,'null')||'/'||team_short_name, ' ; ') from Team group by 1 having count(*)>1;
-- name: player_name_dupes_count
select count(*) names, sum(c) rows, max(c) from (select player_name, count(*) c from Player group by 1 having c>1);
-- name: fk_orphans
select 'Match.country_id' fk, sum(country_id not in (select id from Country)) orphans from Match
union all select 'Match.league_id', sum(league_id not in (select id from League)) from Match
union all select 'Match.league->country consistent', sum((select country_id from League l where l.id=Match.league_id) <> country_id) from Match
union all select 'Match.home_team', sum(home_team_api_id not in (select team_api_id from Team)) from Match
union all select 'Match.away_team', sum(away_team_api_id not in (select team_api_id from Team)) from Match
union all select 'Match.home=away', sum(home_team_api_id=away_team_api_id) from Match
union all select 'PA.player_api_id', sum(player_api_id not in (select player_api_id from Player)) from Player_Attributes
union all select 'PA.player_fifa_api_id', sum(player_fifa_api_id not in (select player_fifa_api_id from Player)) from Player_Attributes
union all select 'PA api/fifa pair matches Player', sum(not exists (select 1 from Player p where p.player_api_id=pa.player_api_id and p.player_fifa_api_id=pa.player_fifa_api_id)) from Player_Attributes pa
union all select 'TA.team_api_id', sum(team_api_id not in (select team_api_id from Team)) from Team_Attributes
union all select 'TA.team_fifa_api_id', sum(team_fifa_api_id not in (select team_fifa_api_id from Team where team_fifa_api_id is not null)) from Team_Attributes
union all select 'TA api/fifa pair matches Team', sum(not exists (select 1 from Team t where t.team_api_id=ta.team_api_id and t.team_fifa_api_id=ta.team_fifa_api_id)) from Team_Attributes ta;
-- name: match_player_orphans
with s(pid) as (
 select home_player_1 from Match union all select home_player_2 from Match union all select home_player_3 from Match union all select home_player_4 from Match
 union all select home_player_5 from Match union all select home_player_6 from Match union all select home_player_7 from Match union all select home_player_8 from Match
 union all select home_player_9 from Match union all select home_player_10 from Match union all select home_player_11 from Match
 union all select away_player_1 from Match union all select away_player_2 from Match union all select away_player_3 from Match union all select away_player_4 from Match
 union all select away_player_5 from Match union all select away_player_6 from Match union all select away_player_7 from Match union all select away_player_8 from Match
 union all select away_player_9 from Match union all select away_player_10 from Match union all select away_player_11 from Match)
select count(*) slots, count(pid) filled, sum(pid is not null and pid not in (select player_api_id from Player)) orphan_slots,
  count(distinct pid) distinct_players from s;
-- name: coverage
select 'players with attributes' k, count(*) from Player p where exists (select 1 from Player_Attributes a where a.player_api_id=p.player_api_id)
union all select 'players in any match', count(*) from Player p where p.player_api_id in (
 select home_player_1 from Match union select home_player_2 from Match union select home_player_3 from Match union select home_player_4 from Match
 union select home_player_5 from Match union select home_player_6 from Match union select home_player_7 from Match union select home_player_8 from Match
 union select home_player_9 from Match union select home_player_10 from Match union select home_player_11 from Match
 union select away_player_1 from Match union select away_player_2 from Match union select away_player_3 from Match union select away_player_4 from Match
 union select away_player_5 from Match union select away_player_6 from Match union select away_player_7 from Match union select away_player_8 from Match
 union select away_player_9 from Match union select away_player_10 from Match union select away_player_11 from Match)
union all select 'teams in any match', count(*) from Team t where t.team_api_id in (select home_team_api_id from Match union select away_team_api_id from Match)
union all select 'teams with attributes', count(*) from Team t where exists (select 1 from Team_Attributes a where a.team_api_id=t.team_api_id)
union all select 'teams in match but no attributes', count(*) from Team t where t.team_api_id in (select home_team_api_id from Match union select away_team_api_id from Match) and not exists (select 1 from Team_Attributes a where a.team_api_id=t.team_api_id);
-- name: rowid_order
select 'Match id=rowid' k, sum(id<>rowid) from Match union all select 'Player', sum(id<>rowid) from Player
union all select 'PA', sum(id<>rowid) from Player_Attributes union all select 'Team', sum(id<>rowid) from Team;
-- name: pa_order
select 'PA id order by (player_fifa_api_id?)' k, sum(f < pf) breaks from (select player_fifa_api_id f, lag(player_fifa_api_id) over (order by id) pf from Player_Attributes)
union all select 'PA id order by player_name (via Player)', sum(n < pn) from (select p.player_name n, lag(p.player_name) over (order by a.id) pn from Player_Attributes a join Player p using(player_api_id))
union all select 'PA within player: date descending breaks', sum(d > pd) from (select date d, player_api_id pid, lag(date) over (order by id) pd, lag(player_api_id) over (order by id) ppid from Player_Attributes) where pid=ppid
union all select 'PA player blocks contiguous: player changes', sum(pid<>ppid) from (select player_api_id pid, lag(player_api_id) over (order by id) ppid from Player_Attributes)
union all select 'Player id order by name breaks', sum(n < pn) from (select player_name n, lag(player_name) over (order by id) pn from Player)
union all select 'TA id order: team changes', sum(t<>pt) from (select team_api_id t, lag(team_api_id) over (order by id) pt from Team_Attributes)
union all select 'TA within team: date desc? (asc breaks)', sum(d < pd) from (select date d, team_api_id t, lag(date) over (order by id) pd, lag(team_api_id) over (order by id) pt from Team_Attributes) where t=pt;
-- name: match_id_order
select 'Match id vs (country,league)' k, sum(l < pl) from (select league_id l, lag(league_id) over (order by id) pl from Match)
union all select 'Match id vs season within league', sum(s<ps) from (select league_id l, season s, lag(league_id) over (order by id) pl, lag(season) over (order by id) ps from Match) where l=pl
union all select 'Match id vs stage within league-season', sum(st<pst) from (select league_id l, season s, stage st, lag(league_id) over (order by id) pl, lag(season) over (order by id) ps, lag(stage) over (order by id) pst from Match) where l=pl and s=ps
union all select 'Match id vs date within league-season', sum(d<pd) from (select league_id l, season s, date d, lag(league_id) over (order by id) pl, lag(season) over (order by id) ps, lag(date) over (order by id) pd from Match) where l=pl and s=ps
union all select 'Match id vs match_api_id', sum(a<pa) from (select match_api_id a, lag(match_api_id) over (order by id) pa from Match);
