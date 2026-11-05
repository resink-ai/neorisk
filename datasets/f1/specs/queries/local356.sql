-- local356: drivers overtaken on track more often than they overtook on track, leaving out
-- pit entries and exits, retirements and lap 1 (start movements).
-- No gold SQL; written from the question, with local344's overtake rule (see local344.sql)
-- over every race: a track overtake is one on lap 2 or later where the overtaken driver
-- neither retires on that lap nor pits on it or the lap before. It matches none of the four
-- exec_result variants; the nearest, local356_a (76 names), shares 75 of this answer's 78.
WITH lp AS (
    SELECT p.race_id, p.driver_id, p.lap, p.position, p.lap_type,
           lag(p.position) OVER w AS prev,
           lag(p.lap) OVER w AS prev_lap
    FROM lap_positions p
    WINDOW w AS (PARTITION BY p.race_id, p.driver_id ORDER BY p.lap, p.position, p.lap_type)),
cur AS (SELECT * FROM lp WHERE prev_lap = lap - 1 AND lap >= 2),
ov AS (
    SELECT x.race_id, x.lap, x.driver_id AS overtaken, y.driver_id AS overtaker
    FROM cur x JOIN cur y ON y.race_id = x.race_id AND y.lap = x.lap
    WHERE x.prev < y.prev AND x.position > y.position
      AND x.lap_type NOT LIKE 'Retirement%'
      AND NOT EXISTS (SELECT 1 FROM pit_stops s WHERE s.race_id = x.race_id
                                                  AND s.driver_id = x.driver_id
                                                  AND s.lap IN (x.lap, x.lap - 1))),
n AS (
    SELECT driver_id, sum(was_overtaken) AS was_overtaken, sum(overtook) AS overtook
    FROM (SELECT overtaken AS driver_id, 1 AS was_overtaken, 0 AS overtook FROM ov
          UNION ALL
          SELECT overtaker, 0, 1 FROM ov)
    GROUP BY driver_id)
SELECT d.full_name
FROM n JOIN drivers d USING (driver_id)
WHERE n.was_overtaken > n.overtook
ORDER BY d.full_name;
