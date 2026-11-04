-- Text formats of times and numbers, and whether text columns are functions of integer columns.
-- Run: python3 -I rq.py data/spider2/f1.sqlite q4_formats.sql

-- name: lap_time_text_vs_ms
-- lap_times.time is m:ss.sss of milliseconds (no hour field)
select count(*) n,
  sum(time = (milliseconds / 60000) || ':' || printf('%02d', (milliseconds / 1000) % 60) || '.' || printf('%03d', milliseconds % 1000)) eq_m_ss_sss,
  min(milliseconds) min_ms, max(milliseconds) max_ms, sum(milliseconds >= 3600000) over_1h
from lap_times;

-- name: lap_time_text_bad
select race_id, driver_id, lap, time, milliseconds from lap_times
where time != (milliseconds / 60000) || ':' || printf('%02d', (milliseconds / 1000) % 60) || '.' || printf('%03d', milliseconds % 1000) limit 10;

-- name: pit_duration_text_vs_ms
select count(*) n,
  sum(duration = case when milliseconds < 60000 then (milliseconds / 1000) || '.' || printf('%03d', milliseconds % 1000)
                      else (milliseconds / 60000) || ':' || printf('%02d', (milliseconds / 1000) % 60) || '.' || printf('%03d', milliseconds % 1000) end) eq_rule,
  sum(milliseconds >= 60000) over_1min, min(milliseconds) mn, max(milliseconds) mx,
  sum(time glob '[0-2][0-9]:[0-5][0-9]:[0-5][0-9]') time_hh_mm_ss
from pit_stops;

-- name: pit_duration_bad
select race_id, driver_id, stop, duration, milliseconds from pit_stops
where duration != case when milliseconds < 60000 then (milliseconds / 1000) || '.' || printf('%03d', milliseconds % 1000)
                      else (milliseconds / 60000) || ':' || printf('%02d', (milliseconds / 1000) % 60) || '.' || printf('%03d', milliseconds % 1000) end limit 10;

-- name: pit_stop_time_vs_race_time
-- pit_stops.time is local wall clock; races.time is UTC start. Offset (pit time - race start) of the first stop per race
with f as (select race_id, min(time) t from pit_stops group by 1)
select count(*) races, sum(ra.time is null) race_time_null,
  sum(((strftime('%s', '2000-01-01 ' || f.t) - strftime('%s', '2000-01-01 ' || ra.time)) + 86400) % 86400 < 3 * 3600) first_stop_within_3h_of_utc_start
from f join races ra using(race_id);

-- name: pit_stop_time_order
-- within a race, does stop wall-clock order follow lap order?
select count(*) pairs, sum(b.time < a.time) later_lap_earlier_clock, sum(b.time < a.time and a.time > '20:00:00') of_which_midnight_wrap
from pit_stops a join pit_stops b on b.race_id = a.race_id and b.driver_id = a.driver_id and b.stop = a.stop + 1;

-- name: pit_stop_vs_lap_running_time
-- pit stop clock - race start clock vs running milliseconds at the end of the in-lap (lap_times_ext)
with p as (
  select p.race_id, p.driver_id, p.stop, p.lap, p.time, e.running_milliseconds rm,
         strftime('%s', '2000-01-01 ' || p.time) s from pit_stops p
  left join lap_times_ext e on e.race_id = p.race_id and e.driver_id = p.driver_id and e.lap = p.lap),
z as (select race_id, min(s - rm / 1000.0) z0, max(s - rm / 1000.0) z1, count(*) n from p where rm is not null group by 1)
select count(*) races, sum(z1 - z0 <= 120) spread_le_2min, sum(z1 - z0 <= 600) spread_le_10min, max(z1 - z0) max_spread_s from z;

-- name: results_time_text
-- winner: h:mm:ss.sss of milliseconds; others: '+' gap to the winner
with w as (select race_id, milliseconds wm from results where position_order = 1)
select count(*) timed,
  sum(position_order = 1) winners,
  sum(position_order = 1 and time = (milliseconds / 3600000) || ':' || printf('%02d', (milliseconds / 60000) % 60) || ':' || printf('%02d', (milliseconds / 1000) % 60) || '.' || printf('%03d', milliseconds % 1000)) winner_eq_rule,
  sum(position_order > 1 and time like '+%') plus_gap,
  sum(position_order > 1 and time like '+%' and milliseconds - wm < 60000 and time = '+' || ((milliseconds - wm) / 1000) || '.' || printf('%03d', (milliseconds - wm) % 1000)) gap_lt_1min_eq_rule,
  sum(position_order > 1 and time like '+%' and milliseconds - wm >= 60000) gap_ge_1min,
  sum(position_order > 1 and time like '+%' and milliseconds - wm >= 60000 and time = '+' || ((milliseconds - wm) / 60000) || ':' || printf('%02d', ((milliseconds - wm) / 1000) % 60) || '.' || printf('%03d', (milliseconds - wm) % 1000)) gap_ge_1min_eq_rule
from results r join w using(race_id) where r.time is not null;

-- name: results_time_text_examples
select time, count(*) from results where time is not null and time not glob '+[0-9]*.[0-9][0-9][0-9]' and time not glob '[0-9]:[0-5][0-9]:[0-5][0-9].[0-9][0-9][0-9]' group by 1 order by 2 desc limit 15;

-- name: results_time_ms_null_mismatch
select sum((time is null) != (milliseconds is null)) time_ms_nullness_differs,
       sum(time is not null and milliseconds is null) time_without_ms, sum(time is null and milliseconds is not null) ms_without_time from results;

-- name: position_text_values
select position_text, count(*), sum(position is null) pos_null, min(position_order), max(position_order) from results
where position_text not glob '[0-9]*' group by 1;

-- name: position_vs_text
select sum(position is not null and position_text != cast(position as text)) num_text_differs,
       sum(position is not null and position != position_order) pos_ne_order,
       sum(position is null and position_text glob '[0-9]*') null_pos_numeric_text from results;

-- name: points_values
select points, count(*) from results group by 1 order by 1;

-- name: fastest_lap_fields
select sum(fastest_lap is null) fl_null, sum(rank is null) rank_null, sum(rank = 0) rank_zero,
  sum(fastest_lap is null and rank is not null) rank_without_fl, sum(fastest_lap_time is null) flt_null, sum(fastest_lap_speed is null) fls_null,
  sum(fastest_lap_speed glob '*0') speed_trailing_zero, min(fastest_lap_speed), max(fastest_lap_speed) from results;

-- name: rank_without_fastest_lap
select rank, count(*), min(ra.year), max(ra.year) from results r join races ra using(race_id) where fastest_lap is null and rank is not null group by 1;

-- name: qualifying_text
select sum(q1 = '') q1_empty, sum(q1 is null) q1_null, sum(q2 = '') q2_empty, sum(q2 is null) q2_null, sum(q3 = '') q3_empty, sum(q3 is null) q3_null,
  sum(q1 glob '[0-9]:[0-5][0-9].[0-9][0-9][0-9]') q1_m_ss_sss, sum(q1 is not null and q1 != '' and q1 not glob '[0-9]:[0-5][0-9].[0-9][0-9][0-9]') q1_other from qualifying;

-- name: qualifying_odd
select q1, count(*) from qualifying where q1 is not null and q1 not glob '[0-9]:[0-5][0-9].[0-9][0-9][0-9]' group by 1 limit 10;

-- name: qualifying_empty_by_year
select ra.year, sum(q2 = '') q2_empty, sum(q3 = '') q3_empty, sum(q2 is null) q2_null, sum(q3 is null) q3_null from qualifying q join races ra using(race_id) group by 1 having q2_empty + q3_empty > 0;

-- name: race_time_formats
select sum(time glob '[0-2][0-9]:[0-5][0-9]:[0-5][0-9]') hh_mm_ss, sum(time is null) null_time,
  min(case when time is not null then year end) first_year_with_time,
  sum(date glob '[12][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]') date_iso,
  sum(fp1_date is not null) fp1, sum(quali_date is not null) quali_date, min(case when quali_date is not null then year end) first_year_quali_date,
  sum(quali_date is not null and quali_date >= date) quali_not_before_race, sum(sprint_date is not null and sprint_date >= date) sprint_not_before_race
from races;

-- name: race_time_by_year
select year, count(*) races, sum(time is not null) with_time, sum(fp1_date is not null) with_fp1 from races group by 1 having with_time > 0 and with_time < races or year in (2005, 2021, 2022);

-- name: session_offsets
-- session dates relative to race date (days)
select 'quali' s, cast(julianday(date) - julianday(quali_date) as int) d, count(*) from races where quali_date is not null group by 2
union all select 'fp1', cast(julianday(date) - julianday(fp1_date) as int), count(*) from races where fp1_date is not null group by 2
union all select 'sprint', cast(julianday(date) - julianday(sprint_date) as int), count(*) from races where sprint_date is not null group by 2;

-- name: dob_formats
select sum(dob glob '[12][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]') iso, count(*) n, min(dob), max(dob) from drivers;

-- name: real_columns
select 'circuits.lat' c, sum(lat != round(lat, 6)) more_than_6dp, min(lat), max(lat) from circuits
union all select 'circuits.lng', sum(lng != round(lng, 6)), min(lng), max(lng) from circuits
union all select 'results.points', sum(points * 100 != cast(points * 100 as int)), min(points), max(points) from results
union all select 'driver_standings.points', sum(points * 100 != cast(points * 100 as int)), min(points), max(points) from driver_standings
union all select 'constructor_standings.points', sum(points * 100 != cast(points * 100 as int)), min(points), max(points) from constructor_standings;

-- name: fractional_points
select points, count(*) from results where points != cast(points as int) group by 1 order by 2 desc;

-- name: constructor_results_status
select cr.status, ra.year, c.constructor_ref, count(*) from constructor_results cr join races ra using(race_id) join constructors c using(constructor_id) where cr.status is not null group by 1,2,3;

-- name: standings_position_text
select 'driver' t, position_text, count(*) from driver_standings where position_text != cast(position as text) group by 2
union all select 'constructor', position_text, count(*) from constructor_standings where position_text != cast(position as text) group by 2;

-- name: liveries
select constructor_ref, start_year, end_year, primary_hex_code from liveries where constructor_ref not in (select constructor_ref from constructors)
union all select '-- end_year null', count(*), null, null from liveries where end_year is null
union all select '-- overlapping spans per ref', count(*), null, null from liveries a join liveries b on a.constructor_ref = b.constructor_ref and a.rowid < b.rowid
   and a.start_year <= coalesce(b.end_year, 9999) and b.start_year <= coalesce(a.end_year, 9999);

-- name: drivers_number_code
select sum(number is null) number_null, sum(code is null) code_null, min(case when code is not null then (select min(ra.year) from results r join races ra using(race_id) where r.driver_id = d.driver_id) end) first_debut_with_code from drivers d;

-- name: lap_times_completeness
-- per (race, driver): laps 1..n contiguous? and n vs results.laps
with a as (select race_id, driver_id, count(*) n, max(lap) mx, min(lap) mn from lap_times group by 1,2)
select count(*) pairs, sum(n = mx and mn = 1) contiguous, sum(exists (select 1 from results r where r.race_id = a.race_id and r.driver_id = a.driver_id and r.laps = a.mx)) eq_results_laps from a;

-- name: lap_times_races_partial
-- races with results 1996+ but no lap_times
select ra.year, count(*) from races ra where ra.year >= 1996 and ra.race_id in (select race_id from results) and ra.race_id not in (select race_id from lap_times) group by 1;

-- name: lap_time_text_rule_with_hours
select count(*) n, sum(time = case when milliseconds < 3600000
    then (milliseconds / 60000) || ':' || printf('%02d', (milliseconds / 1000) % 60) || '.' || printf('%03d', milliseconds % 1000)
    else (milliseconds / 3600000) || ':' || printf('%02d', (milliseconds / 60000) % 60) || ':' || printf('%02d', (milliseconds / 1000) % 60) || '.' || printf('%03d', milliseconds % 1000) end) eq_rule
from lap_times;

-- name: standings_points_off_grid
select 'driver' t, points, printf('%.17g', points) full17, count(*) from driver_standings where points * 100 != cast(points * 100 as int) group by 2
union all select 'results', points, printf('%.17g', points), count(*) from results where points * 100 != cast(points * 100 as int) group by 2;

-- name: winner_time_decimals_by_era
select case when r.time glob '*.[0-9][0-9][0-9]' then '3 decimals' when r.time glob '*.[0-9][0-9]' then '2' when r.time glob '*.[0-9]' then '1' else 'other' end dec,
  min(ra.year), max(ra.year), count(*) from results r join races ra using(race_id) where r.time is not null group by 1;

-- name: position_ne_order
select r.race_id, ra.year, r.driver_id, r.position, r.position_text, r.position_order, r.status_id from results r join races ra using(race_id)
where (r.position is not null and r.position != r.position_order) or (r.position is null and r.position_text glob '[0-9]*') limit 20;
