-- Event-time rules: what times exist, and do the proposed rules order events correctly.
-- Run: python3 -I rq.py data/spider2/f1.sqlite q6_times.sql

-- name: race_start_known
select (ra.time is not null) has_time, count(distinct ra.race_id) races,
  sum(ra.race_id in (select race_id from lap_times)) with_laps_rows from races ra group by 1;

-- name: lap_races_without_start_time
select count(distinct l.race_id) races, min(ra.year), max(ra.year) from lap_times l join races ra using(race_id) where ra.time is null;

-- name: race_start_times
select time, count(*) from races where time is not null group by 1 order by 2 desc limit 8;

-- name: latest_lap_end_vs_next_midnight
-- race start (time or 12:00:00 rule) + running ms: latest lap completion, in hours after midnight of race day
select max((strftime('%s', ra.date || ' ' || coalesce(ra.time, '12:00:00')) - strftime('%s', ra.date) + e.running_milliseconds / 1000.0) / 3600.0) max_hours_after_midnight,
  sum((strftime('%s', ra.date || ' ' || coalesce(ra.time, '12:00:00')) - strftime('%s', ra.date) + e.running_milliseconds / 1000.0) >= 86400) laps_past_midnight
from lap_times_ext e join races ra using(race_id);

-- name: max_running_ms
select max(running_milliseconds) / 3600000.0 max_race_hours from lap_times_ext;

-- name: pit_stop_lap_without_lap_time
-- pit stops whose lap has no lap_times row: fall back to the last earlier lap
select count(*) stops,
  sum(exists (select 1 from lap_times l where l.race_id = p.race_id and l.driver_id = p.driver_id and l.lap < p.lap)) has_earlier_lap,
  sum(not exists (select 1 from lap_times l where l.race_id = p.race_id and l.driver_id = p.driver_id)) driver_no_laps_at_all
from pit_stops p where not exists (select 1 from lap_times l where l.race_id = p.race_id and l.driver_id = p.driver_id and l.lap = p.lap);

-- name: pit_lap_beyond_results_laps
select count(*) from pit_stops p join results r using(race_id, driver_id) where p.lap > r.laps;

-- name: qualifying_time_source
select (ra.quali_date is not null) has_quali_date, (ra.quali_time is not null) has_quali_time, count(*) rows_ from qualifying q join races ra using(race_id) group by 1,2;

-- name: sprint_time_source
select (ra.sprint_time is not null) has_time, count(*) from sprint_results s join races ra using(race_id) group by 1;

-- name: lap_events_same_time
-- ties: identical (race, completion ms) between drivers
select count(*) from (select race_id, running_milliseconds from lap_times_ext group by 1,2 having count(*) > 1);

-- name: pit_stops_without_laps_race
select p.race_id, ra.year, ra.round, ra.name, ra.date, count(*) stops from pit_stops p join races ra using(race_id)
where not exists (select 1 from lap_times l where l.race_id = p.race_id) group by 1;
