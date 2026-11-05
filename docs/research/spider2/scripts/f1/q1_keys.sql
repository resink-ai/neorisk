-- Inventory, keys, joins. Run: python3 -I rq.py data/spider2/f1.sqlite q1_keys.sql

-- name: row_counts
select 'circuits' t, count(*) n from circuits union all select 'constructors', count(*) from constructors
union all select 'drivers', count(*) from drivers union all select 'seasons', count(*) from seasons
union all select 'status', count(*) from status union all select 'races', count(*) from races
union all select 'results', count(*) from results union all select 'sprint_results', count(*) from sprint_results
union all select 'qualifying', count(*) from qualifying union all select 'lap_times', count(*) from lap_times
union all select 'pit_stops', count(*) from pit_stops union all select 'driver_standings', count(*) from driver_standings
union all select 'constructor_standings', count(*) from constructor_standings union all select 'constructor_results', count(*) from constructor_results
union all select 'short_grand_prix_names', count(*) from short_grand_prix_names union all select 'short_constructor_names', count(*) from short_constructor_names
union all select 'liveries', count(*) from liveries union all select 'tdr_overrides', count(*) from tdr_overrides
union all select 'circuits_ext', count(*) from circuits_ext union all select 'constructors_ext', count(*) from constructors_ext
union all select 'drivers_ext', count(*) from drivers_ext union all select 'races_ext', count(*) from races_ext
union all select 'driver_standings_ext', count(*) from driver_standings_ext union all select 'lap_times_ext', count(*) from lap_times_ext
union all select 'lap_time_stats', count(*) from lap_time_stats union all select 'team_driver_ranks', count(*) from team_driver_ranks
union all select 'drives', count(*) from drives union all select 'retirements', count(*) from retirements
union all select 'lap_positions', count(*) from lap_positions;

-- name: natural_key_uniqueness
select 'results (race,driver)' k, count(*) n, count(distinct race_id||'-'||driver_id) d from results
union all select 'results (race,driver,constructor)', count(*), count(distinct race_id||'-'||driver_id||'-'||constructor_id) from results
union all select 'results (race,position_order)', count(*), count(distinct race_id||'-'||position_order) from results
union all select 'sprint_results (race,driver)', count(*), count(distinct race_id||'-'||driver_id) from sprint_results
union all select 'qualifying (race,driver)', count(*), count(distinct race_id||'-'||driver_id) from qualifying
union all select 'driver_standings (race,driver)', count(*), count(distinct race_id||'-'||driver_id) from driver_standings
union all select 'constructor_standings (race,constructor)', count(*), count(distinct race_id||'-'||constructor_id) from constructor_standings
union all select 'constructor_results (race,constructor)', count(*), count(distinct race_id||'-'||constructor_id) from constructor_results
union all select 'races (year,round)', count(*), count(distinct year||'-'||round) from races
union all select 'pit_stops (race,driver,lap)', count(*), count(distinct race_id||'-'||driver_id||'-'||lap) from pit_stops
union all select 'retirements (race,driver)', count(*), count(distinct race_id||'-'||driver_id) from retirements
union all select 'lap_positions (race,driver,lap)', count(*), count(distinct race_id||'-'||driver_id||'-'||lap) from lap_positions
union all select 'drives (year,driver,drive_id,constructor)', count(*), count(distinct year||'-'||driver_id||'-'||drive_id||'-'||constructor_id) from drives
union all select 'driver_standings_ext id', count(*), count(distinct driver_standings_id) from driver_standings_ext;

-- name: fk_orphans
select 'races.circuit_id' fk, count(*) orphans from races where circuit_id not in (select circuit_id from circuits)
union all select 'races.year', count(*) from races where year not in (select year from seasons)
union all select 'results.race_id', count(*) from results where race_id not in (select race_id from races)
union all select 'results.driver_id', count(*) from results where driver_id not in (select driver_id from drivers)
union all select 'results.constructor_id', count(*) from results where constructor_id not in (select constructor_id from constructors)
union all select 'results.status_id', count(*) from results where status_id not in (select status_id from status)
union all select 'sprint_results.status_id', count(*) from sprint_results where status_id not in (select status_id from status)
union all select 'qualifying (race,driver) not in results', count(*) from qualifying q where not exists (select 1 from results r where r.race_id=q.race_id and r.driver_id=q.driver_id)
union all select 'qualifying (race,driver,constructor) not in results', count(*) from qualifying q where not exists (select 1 from results r where r.race_id=q.race_id and r.driver_id=q.driver_id and r.constructor_id=q.constructor_id)
union all select 'sprint (race,driver) not in results', count(*) from sprint_results q where not exists (select 1 from results r where r.race_id=q.race_id and r.driver_id=q.driver_id)
union all select 'lap_times (race,driver) not in results', count(*) from (select distinct race_id, driver_id from lap_times) q where not exists (select 1 from results r where r.race_id=q.race_id and r.driver_id=q.driver_id)
union all select 'pit_stops (race,driver) not in results', count(*) from (select distinct race_id, driver_id from pit_stops) q where not exists (select 1 from results r where r.race_id=q.race_id and r.driver_id=q.driver_id)
union all select 'pit_stops (race,driver,lap) not in lap_times', count(*) from pit_stops p where not exists (select 1 from lap_times l where l.race_id=p.race_id and l.driver_id=p.driver_id and l.lap=p.lap)
union all select 'driver_standings (race,driver) not in results', count(*) from driver_standings q where not exists (select 1 from results r where r.race_id=q.race_id and r.driver_id=q.driver_id)
union all select 'constructor_results (race,cons) not in results', count(*) from constructor_results q where not exists (select 1 from results r where r.race_id=q.race_id and r.constructor_id=q.constructor_id)
union all select 'constructor_standings (race,cons) not in results', count(*) from constructor_standings q where not exists (select 1 from results r where r.race_id=q.race_id and r.constructor_id=q.constructor_id)
union all select 'liveries.constructor_ref', count(*) from liveries where constructor_ref not in (select constructor_ref from constructors)
union all select 'tdr_overrides refs', count(*) from tdr_overrides where constructor_ref not in (select constructor_ref from constructors) or driver_ref not in (select driver_ref from drivers)
union all select 'short_grand_prix_names unused', count(*) from short_grand_prix_names where full_name not in (select name from races)
union all select 'drivers without results', count(*) from drivers where driver_id not in (select driver_id from results)
union all select 'constructors without results', count(*) from constructors where constructor_id not in (select constructor_id from results)
union all select 'circuits without races', count(*) from circuits where circuit_id not in (select circuit_id from races)
union all select 'status unused', count(*) from status where status_id not in (select status_id from results union select status_id from sprint_results)
union all select 'races without results', count(*) from races where race_id not in (select race_id from results);

-- name: coverage_by_table
select 'results' t, min(ra.year) y0, max(ra.year) y1, count(distinct race_id) races from results join races ra using(race_id)
union all select 'qualifying', min(ra.year), max(ra.year), count(distinct race_id) from qualifying join races ra using(race_id)
union all select 'lap_times', min(ra.year), max(ra.year), count(distinct race_id) from lap_times join races ra using(race_id)
union all select 'pit_stops', min(ra.year), max(ra.year), count(distinct race_id) from pit_stops join races ra using(race_id)
union all select 'sprint_results', min(ra.year), max(ra.year), count(distinct race_id) from sprint_results join races ra using(race_id)
union all select 'driver_standings', min(ra.year), max(ra.year), count(distinct race_id) from driver_standings join races ra using(race_id)
union all select 'constructor_standings', min(ra.year), max(ra.year), count(distinct race_id) from constructor_standings join races ra using(race_id)
union all select 'constructor_results', min(ra.year), max(ra.year), count(distinct race_id) from constructor_results join races ra using(race_id);

-- name: snapshot
select max(ra.date) last_race_with_results, (select min(date) from races where race_id not in (select race_id from results)) first_race_without,
       (select count(*) from races where race_id not in (select race_id from results)) races_without_results,
       (select max(ra2.date) from lap_times join races ra2 using(race_id)) last_lap_times,
       (select max(ra2.date) from driver_standings join races ra2 using(race_id)) last_standings
from results join races ra using(race_id);

-- name: races_with_results_missing_tables
-- races in 1958+ (constructor era) with results but no constructor_results / standings
select ra.year, count(*) races,
  sum(not exists (select 1 from driver_standings d where d.race_id = ra.race_id)) no_driver_standings,
  sum(not exists (select 1 from constructor_standings d where d.race_id = ra.race_id)) no_constructor_standings,
  sum(not exists (select 1 from constructor_results d where d.race_id = ra.race_id)) no_constructor_results
from races ra where ra.race_id in (select race_id from results) group by 1 having no_driver_standings + no_constructor_standings + no_constructor_results > 0;

-- name: rowid_order
select 'results by result_id' t, sum(result_id < lag) bad from (select result_id, lag(result_id) over (order by rowid) lag from results)
union all select 'races by race_id', sum(race_id < lag) from (select race_id, lag(race_id) over (order by rowid) lag from races)
union all select 'lap_times by (race,driver,lap)', sum(k < lag) from (select race_id*1000000+driver_id*1000+lap k, lag(race_id*1000000+driver_id*1000+lap) over (order by rowid) lag from lap_times)
union all select 'driver_standings by id', sum(driver_standings_id < lag) from (select driver_standings_id, lag(driver_standings_id) over (order by rowid) lag from driver_standings);

-- name: race_id_vs_date
-- race_id is not chronological
select count(*) pairs, sum(b.date < a.date) id_later_but_earlier_date from races a join races b on b.race_id = a.race_id + 1;
