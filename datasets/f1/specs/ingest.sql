-- F1: source tables → events (refdata ingest). Times are UTC; N = 2024-07-08 00:00:00, the
-- classification of the last race with results. The 11 derived tables and the 3 generated
-- columns produce no events.

-- entity: circuits
-- Created at Jan 1 of the circuit's first race year.
SELECT c.circuit_id AS ext_id, c.circuit_ref, c.name, c.location, c.country, c.lat, c.lng,
       c.alt, c.url,
       (SELECT min(r.year) FROM races r WHERE r.circuit_id = c.circuit_id) || '-01-01 00:00:00'
           AS created_at
FROM circuits c ORDER BY c.circuit_id;

-- entity: constructors
-- Created at Jan 1 of the first year it is classified, scored or ranked; the unused one at
-- 1950-01-01.
SELECT c.constructor_id AS ext_id, c.constructor_ref, c.name, c.nationality, c.url,
       coalesce((SELECT min(r.year) FROM races r JOIN (
                     SELECT race_id, constructor_id FROM results
                     UNION ALL SELECT race_id, constructor_id FROM qualifying
                     UNION ALL SELECT race_id, constructor_id FROM sprint_results
                     UNION ALL SELECT race_id, constructor_id FROM constructor_results
                     UNION ALL SELECT race_id, constructor_id FROM constructor_standings) u
                 USING (race_id) WHERE u.constructor_id = c.constructor_id), 1950)
           || '-01-01 00:00:00' AS created_at
FROM constructors c ORDER BY c.constructor_id;

-- entity: drivers
-- Created at Jan 1 of the first year with a result or a qualifying row.
SELECT d.driver_id AS ext_id, d.driver_ref, d.number, d.code, d.forename, d.surname, d.dob,
       d.nationality, d.url,
       (SELECT min(r.year) FROM races r JOIN (
            SELECT race_id, driver_id FROM results
            UNION ALL SELECT race_id, driver_id FROM qualifying) u
        USING (race_id) WHERE u.driver_id = d.driver_id) || '-01-01 00:00:00' AS created_at
FROM drivers d ORDER BY d.driver_id;

-- entity: seasons
SELECT year AS ext_id, url, year || '-01-01 00:00:00' AS created_at
FROM seasons ORDER BY year;

-- entity: status
SELECT status_id AS ext_id, status, '1950-01-01 00:00:00' AS created_at
FROM status ORDER BY status_id;

-- entity: short_grand_prix_names
SELECT full_name AS ext_id, short_name, '1950-01-01 00:00:00' AS created_at
FROM short_grand_prix_names ORDER BY full_name;

-- entity: short_constructor_names
SELECT constructor_ref AS ext_id, short_name, '1950-01-01 00:00:00' AS created_at
FROM short_constructor_names ORDER BY constructor_ref;

-- entity: liveries
-- Created at Jan 1 of start_year; end_year is a snapshot value.
SELECT constructor_ref || '/' || start_year AS ext_id, constructor_ref, start_year, end_year,
       primary_hex_code, start_year || '-01-01 00:00:00' AS created_at
FROM liveries ORDER BY constructor_ref, start_year;

-- entity: tdr_overrides
-- Hand judgements made after the seasons: created at N.
SELECT year || '/' || constructor_ref || '/' || driver_ref AS ext_id, year, constructor_ref,
       driver_ref, team_driver_rank, '2024-07-08 00:00:00' AS created_at
FROM tdr_overrides ORDER BY year, constructor_ref, driver_ref;

-- event: race_scheduled owner=circuit_id ord=race_id
-- At Jan 1 of the season (no calendar publication date exists).
SELECT year || '-01-01 00:00:00' AS event_time, circuit_id, race_id, year, round, name, date,
       time, url, fp1_date, fp1_time, fp2_date, fp2_time, fp3_date, fp3_time, quali_date,
       quali_time, sprint_date, sprint_time
FROM races ORDER BY year, round;

-- event: qualifying_classified owner=driver_id ord=race_id
-- At the qualifying session (12:00 when it has no time); before 2021, the day before the race
-- at 12:00.
SELECT coalesce(r.quali_date || ' ' || coalesce(r.quali_time, '12:00:00'),
                date(r.date, '-1 day') || ' 12:00:00') AS event_time,
       q.driver_id, q.qualify_id, q.race_id, q.constructor_id, q.number, q.position, q.q1,
       q.q2, q.q3
FROM qualifying q JOIN races r USING (race_id)
ORDER BY q.race_id, q.position, q.qualify_id;

-- event: sprint_classified owner=driver_id ord=race_id
-- At the sprint session; 12:00 when it has no time.
SELECT r.sprint_date || ' ' || coalesce(r.sprint_time, '12:00:00') AS event_time,
       s.driver_id, s.result_id, s.race_id, s.constructor_id, s.number, s.grid, s.position,
       s.position_text, s.position_order, s.points, s.laps, s.time, s.milliseconds,
       s.fastest_lap, s.fastest_lap_time, s.fastest_lap_speed, s.status_id
FROM sprint_results s JOIN races r USING (race_id)
ORDER BY s.race_id, s.position_order, s.result_id;

-- event: lap_completed owner=driver_id ord=race_id
-- At race start + the driver's running milliseconds; the start is 12:00 for the races with no
-- time (all before 2005).
WITH l AS (
    SELECT l.*, sum(l.milliseconds) OVER (PARTITION BY l.race_id, l.driver_id ORDER BY l.lap)
               AS running_ms,
           strftime('%s', r.date || ' ' || coalesce(r.time, '12:00:00')) AS start_s
    FROM lap_times l JOIN races r USING (race_id))
SELECT datetime(start_s + running_ms / 1000, 'unixepoch') || '.'
           || printf('%03d', running_ms % 1000) AS event_time,
       driver_id, race_id, lap, position, milliseconds
FROM l ORDER BY race_id, running_ms, driver_id;

-- event: pit_stop_made owner=driver_id ord=race_id
-- At the in-lap's lap_completed time. Race 1132 has no laps: start + (the stop's local clock -
-- the race's first stop clock).
WITH l AS (
    SELECT race_id, driver_id, lap,
           sum(milliseconds) OVER (PARTITION BY race_id, driver_id ORDER BY lap) AS running_ms
    FROM lap_times),
p AS (
    SELECT p.*, l.running_ms,
           strftime('%s', r.date || ' ' || coalesce(r.time, '12:00:00')) AS start_s,
           strftime('%s', '2000-01-01 ' || p.time)
               - strftime('%s', '2000-01-01 ' || min(p.time) OVER (PARTITION BY p.race_id))
               AS clock_s
    FROM pit_stops p JOIN races r USING (race_id)
    LEFT JOIN l ON l.race_id = p.race_id AND l.driver_id = p.driver_id AND l.lap = p.lap)
SELECT CASE WHEN running_ms IS NULL THEN datetime(start_s + clock_s, 'unixepoch')
            ELSE datetime(start_s + running_ms / 1000, 'unixepoch') || '.'
                     || printf('%03d', running_ms % 1000) END AS event_time,
       driver_id, race_id, stop, lap, time, milliseconds
FROM p ORDER BY race_id, driver_id, stop;

-- event: race_result_classified owner=driver_id ord=race_id
-- At race day + 1, 00:00 (no lap ends after 22:04 on race day).
SELECT date(r.date, '+1 day') || ' 00:00:00' AS event_time,
       s.driver_id, s.result_id, s.race_id, s.constructor_id, s.number, s.grid, s.position,
       s.position_text, s.position_order, s.points, s.laps, s.time, s.milliseconds,
       s.fastest_lap, s.rank, s.fastest_lap_time, s.fastest_lap_speed, s.status_id
FROM results s JOIN races r USING (race_id)
ORDER BY s.race_id, s.position_order, s.result_id;

-- event: constructor_race_points_reported owner=constructor_id ord=race_id
-- With the classification; this block follows it, so it sorts after it.
SELECT date(r.date, '+1 day') || ' 00:00:00' AS event_time,
       c.constructor_id, c.constructor_results_id, c.race_id, c.points, c.status
FROM constructor_results c JOIN races r USING (race_id)
ORDER BY c.race_id, c.constructor_results_id;

-- event: driver_standings_published owner=driver_id ord=race_id
SELECT date(r.date, '+1 day') || ' 00:00:00' AS event_time,
       d.driver_id, d.driver_standings_id, d.race_id, d.points, d.position, d.position_text,
       d.wins
FROM driver_standings d JOIN races r USING (race_id)
ORDER BY d.race_id, d.driver_standings_id;

-- event: constructor_standings_published owner=constructor_id ord=race_id
SELECT date(r.date, '+1 day') || ' 00:00:00' AS event_time,
       c.constructor_id, c.constructor_standings_id, c.race_id, c.points, c.position,
       c.position_text, c.wins
FROM constructor_standings c JOIN races r USING (race_id)
ORDER BY c.race_id, c.constructor_standings_id;

-- event: drive_override_recorded owner=driver_id
-- At N: the source's drives rows for the 17 (year, driver) seasons whose rows the run-length
-- rule in build.sql does not give (docs/research/spider2/scripts/f1/p4_drives_probe.py; 16
-- have a round driven for two constructors). The other seasons come from the rule.
SELECT '2024-07-08 00:00:00' AS event_time, driver_id, year, drive_id, constructor_id,
       first_round, last_round, is_first_drive_of_season, is_final_drive_of_season
FROM drives
WHERE (year, driver_id) IN (VALUES (1950, 529), (1953, 512), (1953, 518), (1953, 520),
                                   (1953, 521), (1953, 612), (1953, 702), (1954, 556),
                                   (1954, 612), (1954, 702), (1954, 730), (1956, 624),
                                   (1958, 541), (1961, 475), (1961, 486), (1962, 465),
                                   (1978, 229))
ORDER BY year, driver_id, first_round, drive_id, constructor_id;
