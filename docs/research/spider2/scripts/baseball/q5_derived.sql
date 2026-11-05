-- name: setup_indexes
create index i_app on appearances(player_id, year, team_id);
create index i_bat on batting(player_id, year, team_id);
create index i_team on team(year, team_id);
-- name: fielding_outfield_vs_appearances
-- summed over stints vs appearances (player, year, team is not in fielding_outfield, so sum per player-year)
with fo as (select player_id, year, sum(glf) lf, sum(gcf) cf, sum(grf) rf from fielding_outfield group by 1,2),
 ap as (select player_id, year, sum(g_lf) lf, sum(g_cf) cf, sum(g_rf) rf from appearances group by 1,2)
select count(*) n, sum(fo.lf=ap.lf and fo.cf=ap.cf and fo.rf=ap.rf) all_eq, sum(ap.player_id is null) no_app from fo left join ap using(player_id, year);
-- name: team_vs_batting_sums
with b as (select year, team_id, sum(r) r, sum(h) h, sum(hr) hr, sum(ab) ab, sum(bb) bb from batting group by 1,2)
select count(*) n, sum(t.r=b.r) r_eq, sum(t.h=b.h) h_eq, sum(t.hr=b.hr) hr_eq, sum(t.ab=b.ab) ab_eq, sum(t.bb=b.bb) bb_eq, sum(t.r=b.r and t.h=b.h and t.hr=b.hr and t.ab=b.ab and t.bb=b.bb) all5 from team t join b using(year, team_id);
-- name: team_vs_pitching_sums
with p as (select year, team_id, sum(w) w, sum(l) l, sum(so) so, sum(ipouts) ip, sum(er) er from pitching group by 1,2)
select count(*) n, sum(t.w=p.w) w_eq, sum(t.l=p.l) l_eq, sum(t.soa=p.so) soa_eq, sum(t.ipouts=p.ip) ipouts_eq, sum(t.er=p.er) er_eq from team t join p using(year, team_id);
-- name: team_vs_manager_sums
with m as (select year, team_id, sum(w) w, sum(l) l, sum(g) g from manager group by 1,2)
select count(*) n, sum(t.w=m.w) w_eq, sum(t.l=m.l) l_eq, sum(t.g=m.g) g_eq from team t join m using(year, team_id);
-- name: team_vs_home_game_attendance
with h as (select year, team_id, sum(attendance) a, sum(games) g from home_game group by 1,2)
select count(*) n, sum(t.attendance<>'' and t.attendance=h.a) att_eq, sum(t.attendance<>'') team_att_present, sum(t.ghome<>'' and t.ghome=h.g) ghome_eq, sum(t.ghome<>'') ghome_present from team t join h using(year, team_id);
-- name: team_half_vs_team
with h as (select year, team_id, sum(w) w, sum(l) l, sum(g) g from team_half group by 1,2)
select count(*) n, sum(t.w=h.w and t.l=h.l and t.g=h.g) wlg_eq from team t join h using(year, team_id);
-- name: manager_half_vs_manager
with h as (select player_id, year, team_id, inseason, sum(w) w, sum(l) l, sum(g) g from manager_half group by 1,2,3,4)
select count(*) n, sum(m.w=h.w and m.l=h.l and m.g=h.g) wlg_eq from manager m join h using(player_id, year, team_id, inseason);
-- name: appearances_g_batting_vs_batting_g
with b as (select player_id, year, team_id, sum(g) g from batting group by 1,2,3)
select count(*) n, sum(a.g_batting=b.g) eq, sum(a.g_all=b.g) g_all_eq from appearances a join b using(player_id, year, team_id);
-- name: appearances_g_p_vs_pitching_g
with p as (select player_id, year, team_id, sum(g) g from pitching group by 1,2,3)
select count(*) n, sum(a.g_p=p.g) eq from appearances a join p using(player_id, year, team_id);
-- name: postseason_wins_vs_lines
select count(*) n, sum(wins + losses + ties between 1 and 10) plausible from postseason;
-- name: player_award_vote_winner_in_award
-- the vote winner (max points) should hold the award of the same name
with w as (select award_id, year, league_id, player_id from player_award_vote v where points_won=(select max(points_won) from player_award_vote x where x.award_id=v.award_id and x.year=v.year and x.league_id=v.league_id))
select w.award_id, count(*) n, sum(exists(select 1 from player_award a where a.player_id=w.player_id and a.year=w.year and (a.award_id=w.award_id or (w.award_id='MVP' and a.award_id='Most Valuable Player') or (w.award_id='Cy Young' and a.award_id='Cy Young Award') or a.award_id like w.award_id||'%'))) in_award from w group by 1;
-- name: player_award_ids
select award_id, count(*), min(year), max(year) from player_award group by 1 order by 2 desc;
