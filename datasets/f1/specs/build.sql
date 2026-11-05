-- F1: events → source tables (refdata rebuild, DuckDB). Ids come back through each entity's
-- ext_id. The generated columns (drivers.full_name, lap_times.seconds, pit_stops.seconds) are
-- left to SQLite. The derived tables follow docs/research/spider2/scripts/f1/q3_derived.sql.

-- table: circuits
SELECT CAST(c.ext_id AS BIGINT) AS circuit_id, c.circuit_ref, s.name, c.location, c.country, c.lat,
       c.lng, c.alt, s.url
FROM circuits c LEFT JOIN circuits_snapshot s USING (circuit_id);

-- table: constructors
SELECT CAST(c.ext_id AS BIGINT) AS constructor_id, c.constructor_ref, c.name, c.nationality, s.url
FROM constructors c LEFT JOIN constructors_snapshot s USING (constructor_id);

-- table: drivers
SELECT CAST(d.ext_id AS BIGINT) AS driver_id, d.driver_ref, s.number, s.code, d.forename, d.surname,
       d.dob, d.nationality, s.url
FROM drivers d LEFT JOIN drivers_snapshot s USING (driver_id);

-- table: seasons
SELECT CAST(x.ext_id AS BIGINT) AS year, s.url
FROM seasons x LEFT JOIN seasons_snapshot s USING (season_id);

-- table: status
SELECT CAST(ext_id AS BIGINT) AS status_id, status FROM status;

-- table: short_grand_prix_names
SELECT ext_id AS full_name, short_name FROM short_grand_prix_names;

-- table: short_constructor_names
SELECT ext_id AS constructor_ref, short_name FROM short_constructor_names;

-- table: liveries
SELECT l.constructor_ref, l.start_year, s.end_year, l.primary_hex_code
FROM liveries l LEFT JOIN liveries_snapshot s USING (livery_id);

-- table: tdr_overrides
SELECT year, constructor_ref, driver_ref, team_driver_rank FROM tdr_overrides;

-- table: races
SELECT r.race_id, r.year, r.round, CAST(c.ext_id AS BIGINT) AS circuit_id, r.name, r.date, r.time, r.url,
       r.fp1_date, r.fp1_time, r.fp2_date, r.fp2_time, r.fp3_date, r.fp3_time, r.quali_date,
       r.quali_time, r.sprint_date, r.sprint_time
FROM race_scheduled r JOIN circuits c USING (circuit_id);

-- table: qualifying
SELECT q.qualify_id, q.race_id, CAST(d.ext_id AS BIGINT) AS driver_id, CAST(c.ext_id AS BIGINT) AS constructor_id, q.number,
       q.position, q.q1, q.q2, q.q3
FROM qualifying_classified q JOIN drivers d USING (driver_id)
JOIN constructors c USING (constructor_id);

-- table: results
SELECT s.result_id, s.race_id, CAST(d.ext_id AS BIGINT) AS driver_id, CAST(c.ext_id AS BIGINT) AS constructor_id, s.number,
       s.grid, s.position, s.position_text, s.position_order, s.points, s.laps, s.time,
       s.milliseconds, s.fastest_lap, s.rank, s.fastest_lap_time, s.fastest_lap_speed,
       CAST(t.ext_id AS BIGINT) AS status_id
FROM race_result_classified s JOIN drivers d USING (driver_id)
JOIN constructors c USING (constructor_id) JOIN status t USING (status_id);

-- table: sprint_results
SELECT s.result_id, s.race_id, CAST(d.ext_id AS BIGINT) AS driver_id, CAST(c.ext_id AS BIGINT) AS constructor_id, s.number,
       s.grid, s.position, s.position_text, s.position_order, s.points, s.laps, s.time,
       s.milliseconds, s.fastest_lap, s.fastest_lap_time, s.fastest_lap_speed,
       CAST(t.ext_id AS BIGINT) AS status_id
FROM sprint_classified s JOIN drivers d USING (driver_id)
JOIN constructors c USING (constructor_id) JOIN status t USING (status_id);

-- table: lap_times
-- time is m:ss.sss of milliseconds, h:mm:ss.sss from one hour (43 red-flag laps).
SELECT l.race_id, CAST(d.ext_id AS BIGINT) AS driver_id, l.lap, l.position,
       CASE WHEN l.milliseconds >= 3600000
            THEN printf('%d:%02d:%02d.%03d', l.milliseconds // 3600000,
                        l.milliseconds // 60000 % 60, l.milliseconds // 1000 % 60,
                        l.milliseconds % 1000)
            ELSE printf('%d:%02d.%03d', l.milliseconds // 60000, l.milliseconds // 1000 % 60,
                        l.milliseconds % 1000) END AS time,
       l.milliseconds
FROM lap_completed l JOIN drivers d USING (driver_id);

-- table: pit_stops
-- duration is s.sss of milliseconds below a minute, m:ss.sss above.
SELECT p.race_id, CAST(d.ext_id AS BIGINT) AS driver_id, p.stop, p.lap, p.time,
       CASE WHEN p.milliseconds < 60000
            THEN printf('%d.%03d', p.milliseconds // 1000, p.milliseconds % 1000)
            ELSE printf('%d:%02d.%03d', p.milliseconds // 60000, p.milliseconds // 1000 % 60,
                        p.milliseconds % 1000) END AS duration,
       p.milliseconds
FROM pit_stop_made p JOIN drivers d USING (driver_id);

-- table: constructor_results
SELECT x.constructor_results_id, x.race_id, CAST(c.ext_id AS BIGINT) AS constructor_id, x.points, x.status
FROM constructor_race_points_reported x JOIN constructors c USING (constructor_id);

-- table: driver_standings
SELECT x.driver_standings_id, x.race_id, CAST(d.ext_id AS BIGINT) AS driver_id, x.points, x.position,
       x.position_text, x.wins
FROM driver_standings_published x JOIN drivers d USING (driver_id);

-- table: constructor_standings
SELECT x.constructor_standings_id, x.race_id, CAST(c.ext_id AS BIGINT) AS constructor_id, x.points,
       x.position, x.position_text, x.wins
FROM constructor_standings_published x JOIN constructors c USING (constructor_id);

-- table: drivers_ext
-- A missing code is the first 3 letters of the surname without spaces, upper-cased in ASCII
-- only (as SQLite's upper()).
SELECT CAST(d.ext_id AS BIGINT) AS driver_id, d.driver_ref, s.number,
       coalesce(s.code, translate(substr(replace(d.surname, ' ', ''), 1, 3),
                                  'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'))
           AS code,
       d.forename, d.surname, d.forename || ' ' || d.surname AS full_name, d.dob, d.nationality,
       s.url
FROM drivers d LEFT JOIN drivers_snapshot s USING (driver_id);

-- table: constructors_ext
SELECT CAST(c.ext_id AS BIGINT) AS constructor_id, c.constructor_ref, c.name, c.nationality, u.url,
       coalesce(s.short_name, c.name) AS short_name
FROM constructors c LEFT JOIN constructors_snapshot u USING (constructor_id)
LEFT JOIN short_constructor_names s ON s.ext_id = c.constructor_ref;

-- table: circuits_ext
-- The race counts include the unraced 2024 rounds.
SELECT CAST(c.ext_id AS BIGINT) AS circuit_id, c.circuit_ref, s.name, c.location, c.country, c.lat, c.lng,
       c.alt, s.url, r.last_race_year, r.number_of_races
FROM circuits c LEFT JOIN circuits_snapshot s USING (circuit_id)
JOIN (SELECT circuit_id, max(year) AS last_race_year, count(*) AS number_of_races
      FROM race_scheduled GROUP BY circuit_id) r USING (circuit_id);

-- table: races_ext
-- max_points is the era's points for a win and fastest lap (a constant per year), plus the
-- sprint win (3 in 2021, 8 after) when the race had a sprint.
WITH r AS (
    SELECT r.*, CAST(c.ext_id AS BIGINT) AS circuit_ext,
           r.race_id IN (SELECT race_id FROM pit_stop_made) AS pit,
           r.race_id IN (SELECT race_id FROM sprint_classified) AS sprint
    FROM race_scheduled r JOIN circuits c USING (circuit_id))
SELECT r.race_id, r.year, r.round, r.circuit_ext AS circuit_id, r.name, r.date, r.time, r.url,
       r.fp1_date, r.fp1_time, r.fp2_date, r.fp2_time, r.fp3_date, r.fp3_time, r.quali_date,
       r.quali_time, r.sprint_date, r.sprint_time,
       CAST(r.pit AS INTEGER) AS is_pit_data_available,
       coalesce(g.short_name, r.name) AS short_name, CAST(r.sprint AS INTEGER) AS has_sprint,
       CASE WHEN r.year < 1960 THEN 9 WHEN r.year = 1960 THEN 8 WHEN r.year <= 1990 THEN 9
            WHEN r.year <= 2009 THEN 10 WHEN r.year <= 2018 THEN 25 ELSE 26 END
       + CASE WHEN r.sprint THEN CASE WHEN r.year = 2021 THEN 3 ELSE 8 END ELSE 0 END
           AS max_points
FROM r LEFT JOIN short_grand_prix_names g ON g.ext_id = r.name;

-- table: lap_times_ext
SELECT l.race_id, CAST(d.ext_id AS BIGINT) AS driver_id, l.lap, l.position,
       CASE WHEN l.milliseconds >= 3600000
            THEN printf('%d:%02d:%02d.%03d', l.milliseconds // 3600000,
                        l.milliseconds // 60000 % 60, l.milliseconds // 1000 % 60,
                        l.milliseconds % 1000)
            ELSE printf('%d:%02d.%03d', l.milliseconds // 60000, l.milliseconds // 1000 % 60,
                        l.milliseconds % 1000) END AS time,
       l.milliseconds, l.milliseconds / 1000.0 AS seconds,
       sum(l.milliseconds) OVER (PARTITION BY l.race_id, l.driver_id ORDER BY l.lap)
           AS running_milliseconds
FROM lap_completed l JOIN drivers d USING (driver_id);

-- table: lap_time_stats
-- avg_seconds is the left-to-right sum of seconds in lap order over n; the stdevs are the
-- population stdev from exact integer sums (within 1e-9 of the source's correctly rounded
-- values; seconds = milliseconds / 1000).
WITH s AS (
    SELECT l.race_id, CAST(d.ext_id AS BIGINT) AS driver_id, count(*) AS n,
           sum(l.milliseconds)::HUGEINT AS sx,
           sum(l.milliseconds::HUGEINT * l.milliseconds) AS sxx,
           list_reduce(list(l.milliseconds / 1000.0 ORDER BY l.lap), (a, b) -> a + b) AS ssec
    FROM lap_completed l JOIN drivers d USING (driver_id)
    GROUP BY l.race_id, CAST(d.ext_id AS BIGINT))
SELECT race_id, driver_id, sx::DOUBLE / n AS avg_milliseconds, ssec / n AS avg_seconds,
       sqrt((n * sxx - sx * sx)::DOUBLE / (n * n)) AS stdev_milliseconds,
       sqrt((n * sxx - sx * sx)::DOUBLE / (n * n)) / 1000 AS stdev_seconds
FROM s;

-- table: driver_standings_ext
-- The standings, plus a 0-point row for each (race, driver) with a result but no standings
-- row, when the driver has a standings row later that season: id 0, no position_text, and a
-- position after the race's last one, dense-ranked by surname (byte order,
-- DuckDB's default).
WITH ds AS (
    SELECT x.driver_standings_id, x.race_id, CAST(d.ext_id AS BIGINT) AS driver_id, x.points, x.position,
           x.position_text, x.wins, r.year, r.round
    FROM driver_standings_published x JOIN drivers d USING (driver_id)
    JOIN race_scheduled r USING (race_id)),
miss AS (
    SELECT DISTINCT x.race_id, CAST(d.ext_id AS BIGINT) AS driver_id, d.surname
    FROM race_result_classified x JOIN drivers d USING (driver_id)
    JOIN race_scheduled r USING (race_id)
    WHERE NOT EXISTS (SELECT 1 FROM ds WHERE ds.race_id = x.race_id
                                         AND ds.driver_id = CAST(d.ext_id AS BIGINT))
      AND EXISTS (SELECT 1 FROM ds WHERE ds.driver_id = CAST(d.ext_id AS BIGINT) AND ds.year = r.year
                                     AND ds.round > r.round))
SELECT driver_standings_id, race_id, driver_id, points, position, position_text, wins FROM ds
UNION ALL
SELECT 0, m.race_id, m.driver_id, 0.0,
       (SELECT max(position) FROM ds WHERE ds.race_id = m.race_id)
           + dense_rank() OVER (PARTITION BY m.race_id ORDER BY m.surname),
       NULL, 0
FROM miss m;

-- table: team_driver_ranks
-- Each team-season's drivers ranked by their final standings position that season (their last
-- standings row); tdr_overrides replaces the rank. Drivers with no standings that season are
-- left out.
WITH ds AS (
    SELECT x.driver_id, x.position, r.year, r.round
    FROM driver_standings_published x JOIN race_scheduled r USING (race_id)),
fin AS (
    SELECT year, driver_id, position FROM ds
    QUALIFY round = max(round) OVER (PARTITION BY year, driver_id)),
yc AS (
    SELECT DISTINCT r.year, x.constructor_id, x.driver_id
    FROM race_result_classified x JOIN race_scheduled r USING (race_id)),
ranked AS (
    SELECT yc.year, CAST(c.ext_id AS BIGINT) AS constructor_id, c.constructor_ref, CAST(d.ext_id AS BIGINT) AS driver_id,
           d.driver_ref,
           row_number() OVER (PARTITION BY yc.year, yc.constructor_id ORDER BY fin.position)
               AS raw_rank
    FROM yc JOIN fin USING (year, driver_id) JOIN constructors c USING (constructor_id)
    JOIN drivers d USING (driver_id))
SELECT k.year, k.constructor_id, k.constructor_ref, k.driver_id, k.driver_ref,
       coalesce(o.team_driver_rank, k.raw_rank) AS team_driver_rank
FROM ranked k LEFT JOIN tdr_overrides o
    ON o.year = k.year AND o.constructor_ref = k.constructor_ref
   AND o.driver_ref = k.driver_ref;

-- table: drives
-- Per (year, driver), the results in (round, result_id) order cut into runs of one
-- constructor; a gap row (-1, -1) spans the missed rounds between two runs. The 17
-- driver-seasons of drive_override_recorded replace the rule's rows.
WITH x AS (
    SELECT r.year, CAST(d.ext_id AS BIGINT) AS driver_id, r.round, CAST(c.ext_id AS BIGINT) AS constructor_id, x.result_id
    FROM race_result_classified x JOIN race_scheduled r USING (race_id)
    JOIN drivers d USING (driver_id) JOIN constructors c USING (constructor_id)),
cut AS (
    SELECT *, CASE WHEN constructor_id = lag(constructor_id) OVER w THEN 0 ELSE 1 END AS new
    FROM x WINDOW w AS (PARTITION BY year, driver_id ORDER BY round, result_id)),
num AS (
    SELECT *, sum(new) OVER (PARTITION BY year, driver_id ORDER BY round, result_id
                             ROWS UNBOUNDED PRECEDING) AS k
    FROM cut),
runs AS (
    SELECT year, driver_id, k, any_value(constructor_id) AS constructor_id,
           min(round) AS first_round, max(round) AS last_round
    FROM num GROUP BY year, driver_id, k),
runs2 AS (
    SELECT *, max(k) OVER (PARTITION BY year, driver_id) AS n,
           lead(first_round) OVER (PARTITION BY year, driver_id ORDER BY k) AS next_first
    FROM runs),
rule AS (
    SELECT year, driver_id, k AS drive_id, constructor_id, first_round, last_round,
           CASE WHEN k = 1 THEN 1 ELSE 0 END AS is_first_drive_of_season,
           CASE WHEN k = n THEN 1 ELSE 0 END AS is_final_drive_of_season
    FROM runs2
    UNION ALL
    SELECT year, driver_id, -1, -1, last_round + 1, next_first - 1, 0, 0
    FROM runs2 WHERE next_first > last_round + 1),
o AS (
    SELECT o.year, CAST(d.ext_id AS BIGINT) AS driver_id, o.drive_id, o.constructor_id, o.first_round,
           o.last_round, o.is_first_drive_of_season, o.is_final_drive_of_season
    FROM drive_override_recorded o JOIN drivers d USING (driver_id))
SELECT * FROM rule
WHERE NOT EXISTS (SELECT 1 FROM o WHERE o.year = rule.year AND o.driver_id = rule.driver_id)
UNION ALL
SELECT * FROM o;

-- table: retirements
-- Results not Finished and not '+n Lap(s)': lap = laps + 1, typed by status.
SELECT x.race_id, CAST(d.ext_id AS BIGINT) AS driver_id, x.laps + 1 AS lap, x.position_order,
       CAST(t.ext_id AS BIGINT) AS status_id,
       CASE WHEN CAST(t.ext_id AS BIGINT) = 2 THEN 'Retirement (Disqualification)'
            WHEN CAST(t.ext_id AS BIGINT) IN (3, 4, 20) THEN 'Retirement (Driver Error)'
            ELSE 'Retirement (Mechanical Problem)' END AS retirement_type
FROM race_result_classified x JOIN drivers d USING (driver_id) JOIN status t USING (status_id)
WHERE t.status != 'Finished' AND t.status NOT LIKE '+%';

-- table: lap_positions
-- Race laps; one lap-0 start row per (race, driver) (DISTINCT: shared drives repeat), at the
-- grid slot (the race's entry count for a pit-lane start); and each retirement at its lap.
WITH res AS (
    SELECT x.race_id, x.driver_id, x.grid, x.laps, x.position_order, x.status_id,
           count(*) OVER (PARTITION BY x.race_id) AS entries
    FROM race_result_classified x),
start AS (
    SELECT DISTINCT r.race_id, CAST(d.ext_id AS BIGINT) AS driver_id, 0 AS lap,
           CASE WHEN r.grid = 0 THEN r.entries ELSE r.grid END AS position,
           CASE WHEN q.position IS NULL THEN 'Starting Position - No Qualification'
                WHEN r.grid = 0 THEN 'Starting Position - Pit Lane Start'
                WHEN r.grid > q.position THEN 'Starting Position - Grid Drop'
                WHEN r.grid < q.position THEN 'Starting Position - Grid Increase'
                ELSE 'Starting Position - Qualifying' END AS lap_type
    FROM res r JOIN drivers d USING (driver_id)
    LEFT JOIN qualifying_classified q ON q.race_id = r.race_id AND q.driver_id = r.driver_id)
SELECT l.race_id, CAST(d.ext_id AS BIGINT) AS driver_id, l.lap, l.position, 'Race' AS lap_type
FROM lap_completed l JOIN drivers d USING (driver_id)
UNION ALL
SELECT * FROM start
UNION ALL
SELECT r.race_id, CAST(d.ext_id AS BIGINT), r.laps + 1, r.position_order,
       CASE WHEN CAST(t.ext_id AS BIGINT) = 2 THEN 'Retirement (Disqualification)'
            WHEN CAST(t.ext_id AS BIGINT) IN (3, 4, 20) THEN 'Retirement (Driver Error)'
            ELSE 'Retirement (Mechanical Problem)' END
FROM res r JOIN drivers d USING (driver_id) JOIN status t USING (status_id)
WHERE t.status != 'Finished' AND t.status NOT LIKE '+%';
