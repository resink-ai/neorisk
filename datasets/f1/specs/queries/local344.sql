-- local344: in races with pit stop data, how many overtakes of each type (R, P, S, T).
-- No gold SQL; written from the question and the four labels of Spider2's f1_overtake.md. It
-- reproduces exec_result variant local344_b exactly (P 37423, R 5536, S 2443, T 13431).
-- A driver is overtaken on lap L when they were ahead of another driver on lap L-1 (lap 0 is
-- the start) and are behind them on lap L, over lap_positions (laps, starts, retirements).
-- R: the overtaken driver retires on lap L. P: the overtaken driver pits on lap L (entry) or
-- pitted on lap L-1 (exit). S: lap 1, and the two grid slots differ by at most 2. T: the rest.
-- The 97 (race, driver, lap) keys that repeat (shared drives) are ordered by position, type.
WITH lp AS (
    SELECT p.race_id, p.driver_id, p.lap, p.position, p.lap_type,
           lag(p.position) OVER w AS prev,
           lag(p.lap) OVER w AS prev_lap
    FROM lap_positions p JOIN races_ext r USING (race_id)
    WHERE r.is_pit_data_available = 1
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
        WHEN o.x_type LIKE 'Retirement%' THEN 'R'
        WHEN EXISTS (SELECT 1 FROM pit_stops s WHERE s.race_id = o.race_id
                                                 AND s.driver_id = o.overtaken
                                                 AND s.lap IN (o.lap, o.lap - 1)) THEN 'P'
        WHEN o.lap = 1 AND o.grid_gap <= 2 THEN 'S'
        ELSE 'T' END AS overtake_type
    FROM ov o)
SELECT overtake_type, count(*) AS num_overtakes
FROM typed GROUP BY overtake_type ORDER BY overtake_type;
