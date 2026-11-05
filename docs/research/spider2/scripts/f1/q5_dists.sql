-- Distributions for stage 2. Run: python3 -I rq.py data/spider2/f1.sqlite q5_dists.sql

-- name: races_per_decade
select (year / 10) * 10 decade, count(*) races, round(avg(n), 1) avg_entries, min(n) min_entries, max(n) max_entries
from (select ra.year, ra.race_id, count(r.result_id) n from races ra join results r using(race_id) group by 1,2) group by 1;

-- name: race_weekday
select strftime('%w', date) dow, count(*) from races group by 1;

-- name: race_gap_days
with r as (select year, date, lag(date) over (partition by year order by round) prev from races)
select cast(julianday(date) - julianday(prev) as int) gap_days, count(*) from r where prev is not null group by 1 order by 2 desc limit 12;

-- name: round_vs_date
select count(*) pairs, sum(b.date <= a.date) later_round_not_later_date from races a join races b on b.year = a.year and b.round = a.round + 1;

-- name: status_mix_by_era
select case when ra.year < 1980 then '1950-79' when ra.year < 2000 then '1980-99' when ra.year < 2014 then '2000-13' else '2014-24' end era,
  count(*) entries, round(100.0 * sum(s.status = 'Finished') / count(*), 1) finished_pct,
  round(100.0 * sum(s.status like '+%') / count(*), 1) lapped_pct,
  round(100.0 * sum(s.status in ('Did not qualify', 'Did not prequalify')) / count(*), 1) dnq_pct,
  round(100.0 * sum(s.status != 'Finished' and s.status not like '+%' and s.status not in ('Did not qualify', 'Did not prequalify')) / count(*), 1) retired_pct
from results r join races ra using(race_id) join status s using(status_id) group by 1;

-- name: top_statuses
select s.status, count(*) from results r join status s using(status_id) group by 1 order by 2 desc limit 12;

-- name: laps_per_race
select min(l), round(avg(l), 1), max(l) from (select race_id, max(laps) l from results group by 1);

-- name: lap_ms_quantiles
with x as (select milliseconds m, ntile(100) over (order by milliseconds) q from lap_times)
select q, max(m) from x where q in (1, 5, 25, 50, 75, 95, 99, 100) group by 1;

-- name: lap_ratio_to_driver_median
-- lap time / driver's race average: shape of in-race variation (pit laps, SC)
with a as (select l.milliseconds * 1.0 / s.avg_milliseconds r from lap_times l join lap_time_stats s using(race_id, driver_id)),
x as (select r, ntile(100) over (order by r) q from a)
select q, round(max(r), 4) from x where q in (1, 10, 50, 90, 95, 99, 100) group by 1;

-- name: pit_stops_per_driver_race
select n stops, count(*) from (select race_id, driver_id, count(*) n from pit_stops group by 1,2) group by 1;

-- name: pit_duration_quantiles
with x as (select milliseconds m, ntile(100) over (order by milliseconds) q from pit_stops)
select q, max(m) from x where q in (1, 10, 25, 50, 75, 90, 95, 99, 100) group by 1;

-- name: pit_lap_fraction
-- stop lap / race laps
with x as (select p.lap * 1.0 / (select max(laps) from results r where r.race_id = p.race_id) f from pit_stops p)
select round(f, 1) bucket, count(*) from x group by 1;

-- name: grid_vs_finish
select case when grid = 0 then 'pit/none' when grid <= 3 then '1-3' when grid <= 10 then '4-10' else '11+' end g,
  count(*) n, round(100.0 * sum(position = 1) / count(*), 2) win_pct, round(100.0 * sum(position is not null) / count(*), 1) classified_pct
from results r join races ra using(race_id) where ra.year >= 2000 group by 1;

-- name: entries_per_driver_career
select case when n = 1 then '1' when n <= 5 then '2-5' when n <= 20 then '6-20' when n <= 100 then '21-100' else '100+' end b, count(*)
from (select driver_id, count(distinct race_id) n from results group by 1) group by 1;

-- name: driver_debut_spacing
-- drivers' first race year vs created order: new drivers per year
select first_year / 10 * 10 decade, count(*) new_drivers from (select driver_id, min(ra.year) first_year from results r join races ra using(race_id) group by 1) group by 1;

-- name: qualifying_sessions
select (q1 is not null and q1 != '') + (q2 is not null and q2 != '') + (q3 is not null and q3 != '') sessions, count(*) from qualifying q join races ra using(race_id) where ra.year >= 2006 group by 1;

-- name: entity_first_use
-- entities' first use (for created_at by rule)
select 'drivers' e, count(*) n, min(fy), max(fy) from (select driver_id, min(ra.date) fy from results r join races ra using(race_id) group by 1)
union all select 'constructors', count(*), min(fy), max(fy) from (select constructor_id, min(ra.date) fy from results r join races ra using(race_id) group by 1)
union all select 'circuits', count(*), min(fy), max(fy) from (select circuit_id, min(date) fy from races group by 1);

-- name: drivers_dob_vs_debut
select round(avg((julianday(fy) - julianday(dob)) / 365.25), 1) avg_age_at_debut, round(min((julianday(fy) - julianday(dob)) / 365.25), 1) min_age, round(max((julianday(fy) - julianday(dob)) / 365.25), 1) max_age
from (select d.dob, min(ra.date) fy from results r join races ra using(race_id) join drivers d using(driver_id) group by r.driver_id);
