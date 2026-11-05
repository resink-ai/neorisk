-- local336: overtakes in the first five laps, by category (retirement, pit, start, track).
-- No gold SQL; written from the question and the four labels of Spider2's f1_overtake.md,
-- with local344's rules (see local344.sql) on laps 1 to 5 of every race. It matches none of
-- the four exec_result variants (local336_a-d: Retirement 13, Pit 3435, Start 5407, Track
-- 10613); this gives Pit 3384, Retirement 4252, Start 5294, Track 9745 on the source.
-- The 97 (race, driver, lap) keys that repeat (shared drives) are ordered by position, type.
WITH lp AS (
    SELECT p.race_id, p.driver_id, p.lap, p.position, p.lap_type,
           lag(p.position) OVER w AS prev,
           lag(p.lap) OVER w AS prev_lap
    FROM lap_positions p WHERE p.lap <= 5
    WINDOW w AS (PARTITION BY p.race_id, p.driver_id ORDER BY p.lap, p.position, p.lap_type)),
cur AS (SELECT * FROM lp WHERE prev_lap = lap - 1),
grid AS (SELECT race_id, driver_id, max(grid) AS grid FROM results GROUP BY 1, 2),
ov AS (
    SELECT x.race_id, x.lap, x.driver_id AS overtaken, x.lap_type AS x_type,
           abs(gx.grid - gy.grid) AS grid_gap
    FROM cur x JOIN cur y ON y.race_id = x.race_id AND y.lap = x.lap
    JOIN grid gx ON gx.race_id = x.race_id AND gx.driver_id = x.driver_id
    JOIN grid gy ON gy.race_id = y.race_id AND gy.driver_id = y.driver_id
    WHERE x.prev < y.prev AND x.position > y.position),
typed AS (
    SELECT CASE
        WHEN o.x_type LIKE 'Retirement%' THEN 'Retirement'
        WHEN EXISTS (SELECT 1 FROM pit_stops s WHERE s.race_id = o.race_id
                                                 AND s.driver_id = o.overtaken
                                                 AND s.lap IN (o.lap, o.lap - 1)) THEN 'Pit'
        WHEN o.lap = 1 AND o.grid_gap <= 2 THEN 'Start'
        ELSE 'Track' END AS category
    FROM ov o)
SELECT category, count(*) AS overtake_count
FROM typed GROUP BY category ORDER BY category;
