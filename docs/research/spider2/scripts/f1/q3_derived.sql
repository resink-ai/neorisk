-- Derivation proofs: each block rebuilds one extra table from the Ergast tables (+ named hand tables)
-- and reports n_src, n_rebuilt, rows in src not rebuilt, rows rebuilt not in src (multiset: by row counts).
-- Run: python3 -I rq.py data/spider2/f1.sqlite q3_derived.sql

-- name: drivers_ext
with cand as (
  select driver_id, driver_ref, number, coalesce(code, upper(substr(replace(surname, ' ', ''), 1, 3))) code,
         forename, surname, full_name, dob, nationality, url from drivers),
s as (select *, count(*) c from drivers_ext group by 1,2,3,4,5,6,7,8,9,10),
b as (select *, count(*) c from cand group by 1,2,3,4,5,6,7,8,9,10)
select (select count(*) from drivers_ext) n_src, (select count(*) from cand) n_rebuilt,
  (select count(*) from (select * from s except select * from b)) src_not_rebuilt,
  (select count(*) from (select * from b except select * from s)) rebuilt_not_src,
  (select count(*) from drivers where code is null) codes_filled;

-- name: constructors_ext
with cand as (
  select c.constructor_id, c.constructor_ref, c.name, c.nationality, c.url, coalesce(s.short_name, c.name) short_name
  from constructors c left join short_constructor_names s using(constructor_ref)),
s as (select *, count(*) c from constructors_ext group by 1,2,3,4,5,6),
b as (select *, count(*) c from cand group by 1,2,3,4,5,6)
select (select count(*) from constructors_ext) n_src, (select count(*) from cand) n_rebuilt,
  (select count(*) from (select * from s except select * from b)) src_not_rebuilt,
  (select count(*) from (select * from b except select * from s)) rebuilt_not_src,
  (select count(*) from short_constructor_names where constructor_ref not in (select constructor_ref from constructors)) unused_short_names;

-- name: circuits_ext
with cand as (
  select c.*, (select max(year) from races r where r.circuit_id = c.circuit_id) last_race_year,
         (select count(*) from races r where r.circuit_id = c.circuit_id) number_of_races from circuits c),
s as (select *, count(*) c from circuits_ext group by 1,2,3,4,5,6,7,8,9,10,11),
b as (select *, count(*) c from cand group by 1,2,3,4,5,6,7,8,9,10,11)
select (select count(*) from circuits_ext) n_src, (select count(*) from cand) n_rebuilt,
  (select count(*) from (select * from s except select * from b)) src_not_rebuilt,
  (select count(*) from (select * from b except select * from s)) rebuilt_not_src;

-- name: races_ext
-- max_points is a per-year points-system constant (+ sprint bonus), not computed from results.
with cand as (
  select r.*,
    exists (select 1 from pit_stops p where p.race_id = r.race_id) is_pit_data_available,
    coalesce(g.short_name, r.name) short_name,
    exists (select 1 from sprint_results s where s.race_id = r.race_id) has_sprint,
    case when r.year < 1960 then 9 when r.year = 1960 then 8 when r.year <= 1990 then 9
         when r.year <= 2009 then 10 when r.year <= 2018 then 25 else 26 end
    + case when exists (select 1 from sprint_results s where s.race_id = r.race_id)
           then case when r.year = 2021 then 3 else 8 end else 0 end max_points
  from races r left join short_grand_prix_names g on g.full_name = r.name),
s as (select *, count(*) c from races_ext group by 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22),
b as (select *, count(*) c from cand group by 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22)
select (select count(*) from races_ext) n_src, (select count(*) from cand) n_rebuilt,
  (select count(*) from (select * from s except select * from b)) src_not_rebuilt,
  (select count(*) from (select * from b except select * from s)) rebuilt_not_src,
  (select count(*) from races where sprint_date is not null and race_id not in (select race_id from sprint_results)) sprint_date_but_no_sprint_result;

-- name: races_ext_max_points_vs_results
-- why max_points is a rule: the max points any driver scored in the race, by year band
with m as (select race_id, max(points) mp from results group by 1)
select e.max_points, m.mp max_points_in_results, count(*) races, min(e.year) y0, max(e.year) y1
from races_ext e left join m using(race_id) group by 1,2 order by 4,1,2;

-- name: lap_times_ext
with cand as (select race_id, driver_id, lap, position, time, milliseconds, seconds,
       sum(milliseconds) over (partition by race_id, driver_id order by lap) running_milliseconds from lap_times),
s as (select *, count(*) c from lap_times_ext group by 1,2,3,4,5,6,7,8),
b as (select *, count(*) c from cand group by 1,2,3,4,5,6,7,8)
select (select count(*) from lap_times_ext) n_src, (select count(*) from cand) n_rebuilt,
  (select count(*) from (select * from s except select * from b)) src_not_rebuilt,
  (select count(*) from (select * from b except select * from s)) rebuilt_not_src;

-- name: driver_standings_ext
-- = driver_standings + a 0-point row for each (race, driver) that has a result but no standings row,
--   when the driver has a standings row later in the same season; positions continue after the race's last
--   position, dense_rank by surname (binary collation, equal surnames tie); driver_standings_id 0, position_text NULL.
with miss as (
  select distinct r.race_id, r.driver_id from results r join races ra using(race_id)
  where not exists (select 1 from driver_standings d where d.race_id = r.race_id and d.driver_id = r.driver_id)
    and exists (select 1 from driver_standings d join races q using(race_id) where d.driver_id = r.driver_id and q.year = ra.year and q.round > ra.round)),
added as (
  select 0 driver_standings_id, m.race_id, m.driver_id, 0.0 points,
    (select max(position) from driver_standings d where d.race_id = m.race_id)
      + dense_rank() over (partition by m.race_id order by dr.surname) position,
    null position_text, 0 wins
  from miss m join drivers dr using(driver_id)),
cand as (select * from driver_standings union all select * from added),
s as (select *, count(*) c from driver_standings_ext group by 1,2,3,4,5,6,7),
b as (select *, count(*) c from cand group by 1,2,3,4,5,6,7)
select (select count(*) from driver_standings_ext) n_src, (select count(*) from cand) n_rebuilt, (select count(*) from added) n_added,
  (select count(*) from (select * from s except select * from b)) src_not_rebuilt,
  (select count(*) from (select * from b except select * from s)) rebuilt_not_src;

-- name: driver_standings_gaps
-- results pairs with no standings row: filled by _ext (driver appears later that season) vs not
with miss as (select distinct race_id, driver_id from results except select race_id, driver_id from driver_standings)
select count(*) missing_pairs,
  sum(exists (select 1 from driver_standings_ext e where e.race_id = m.race_id and e.driver_id = m.driver_id)) filled_in_ext,
  sum(not exists (select 1 from driver_standings d join races q using(race_id) join races ra on ra.race_id = m.race_id
                  where d.driver_id = m.driver_id and q.year = ra.year)) driver_never_in_season_standings
from miss m;

-- name: team_driver_ranks
-- rank within (year, constructor) of the drivers who have results for it, ordered by the driver's final
-- standings position that season (last standings row); tdr_overrides (hand data) replaces the rank.
with fin as (
  select ra.year, d.driver_id, d.position from driver_standings d join races ra using(race_id)
  where ra.round = (select max(r2.round) from races r2 join driver_standings d2 using(race_id) where r2.year = ra.year and d2.driver_id = d.driver_id)),
yc as (select distinct ra.year, r.constructor_id, r.driver_id from results r join races ra using(race_id)),
ranked as (
  select yc.year, yc.constructor_id, c.constructor_ref, yc.driver_id, dr.driver_ref,
    row_number() over (partition by yc.year, yc.constructor_id order by fin.position) raw_rank
  from yc join fin using(year, driver_id) join constructors c using(constructor_id) join drivers dr using(driver_id)),
cand as (
  select k.year, k.constructor_id, k.constructor_ref, k.driver_id, k.driver_ref, coalesce(o.team_driver_rank, k.raw_rank) team_driver_rank
  from ranked k left join tdr_overrides o on o.year = k.year and o.constructor_ref = k.constructor_ref and o.driver_ref = k.driver_ref),
s as (select *, count(*) c from team_driver_ranks group by 1,2,3,4,5,6),
b as (select *, count(*) c from cand group by 1,2,3,4,5,6)
select (select count(*) from team_driver_ranks) n_src, (select count(*) from cand) n_rebuilt,
  (select count(*) from (select * from s except select * from b)) src_not_rebuilt,
  (select count(*) from (select * from b except select * from s)) rebuilt_not_src,
  (select count(*) from ranked k join tdr_overrides o on o.year = k.year and o.constructor_ref = k.constructor_ref and o.driver_ref = k.driver_ref) overrides_applied,
  (select count(*) from ranked k join tdr_overrides o on o.year = k.year and o.constructor_ref = k.constructor_ref and o.driver_ref = k.driver_ref where o.team_driver_rank != k.raw_rank) overrides_that_change_rank,
  (select count(*) from yc) year_team_driver_triples, (select count(*) from yc where not exists (select 1 from fin where fin.year = yc.year and fin.driver_id = yc.driver_id)) triples_without_standings;

-- name: retirements
with cand as (
  select r.race_id, r.driver_id, r.laps + 1 lap, r.position_order, r.status_id,
    case when r.status_id = 2 then 'Retirement (Disqualification)'
         when r.status_id in (3, 4, 20) then 'Retirement (Driver Error)'
         else 'Retirement (Mechanical Problem)' end retirement_type
  from results r join status s using(status_id)
  where s.status != 'Finished' and s.status not like '+%'),
s as (select *, count(*) c from retirements group by 1,2,3,4,5,6),
b as (select *, count(*) c from cand group by 1,2,3,4,5,6)
select (select count(*) from retirements) n_src, (select count(*) from cand) n_rebuilt,
  (select count(*) from (select * from s except select * from b)) src_not_rebuilt,
  (select count(*) from (select * from b except select * from s)) rebuilt_not_src;

-- name: lap_positions
-- = lap_times ('Race') + DISTINCT lap-0 start rows from results/qualifying + retirements (lap, position_order).
with start as (
  select distinct r.race_id, r.driver_id, 0 lap,
    case when r.grid = 0 then (select count(*) from results r2 where r2.race_id = r.race_id) else r.grid end position,
    case when q.position is null then 'Starting Position - No Qualification'
         when r.grid = 0 then 'Starting Position - Pit Lane Start'
         when r.grid > q.position then 'Starting Position - Grid Drop'
         when r.grid < q.position then 'Starting Position - Grid Increase'
         else 'Starting Position - Qualifying' end lap_type
  from results r left join qualifying q on q.race_id = r.race_id and q.driver_id = r.driver_id),
cand as (
  select race_id, driver_id, lap, position, 'Race' lap_type from lap_times
  union all select * from start
  union all select race_id, driver_id, lap, position_order, retirement_type from retirements),
s as (select *, count(*) c from lap_positions group by 1,2,3,4,5),
b as (select *, count(*) c from cand group by 1,2,3,4,5)
select (select count(*) from lap_positions) n_src, (select count(*) from cand) n_rebuilt,
  (select count(*) from (select * from s except select * from b)) src_not_rebuilt,
  (select count(*) from (select * from b except select * from s)) rebuilt_not_src,
  (select count(*) from results) - (select count(*) from start) start_rows_collapsed_by_distinct;

-- name: generated_columns
-- the three VIRTUAL columns are functions of their own row
select (select count(*) from drivers where full_name is not forename || ' ' || surname) drivers_full_name_bad,
       (select count(*) from lap_times where seconds is not cast(milliseconds as float) / 1000) lap_seconds_bad,
       (select count(*) from pit_stops where seconds is not cast(milliseconds as float) / 1000) pit_seconds_bad;
