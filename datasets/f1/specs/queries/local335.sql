-- local335: since 2001, among drivers who scored points in a season, the five constructors
-- whose drivers were most often the season's lowest point scorer.
-- No gold SQL; written from the question. It reproduces variant local335_a (Williams 6,
-- Toro Rosso 5, Minardi 3, Sauber 3, Arrows 2), as docs/research/spider2/scripts/f1/p9_gold.py
-- shows. A season's lowest scorer counts for every constructor they drove for that season.
WITH dp AS (
    SELECT ra.year, r.driver_id, sum(r.points) AS p
    FROM results r JOIN races ra USING (race_id)
    WHERE ra.year >= 2001 GROUP BY 1, 2 HAVING sum(r.points) > 0),
mn AS (
    SELECT year, driver_id FROM dp d
    WHERE p = (SELECT min(p) FROM dp d2 WHERE d2.year = d.year)),
dc AS (
    SELECT DISTINCT mn.year, r.constructor_id
    FROM mn JOIN results r ON r.driver_id = mn.driver_id
    JOIN races ra ON ra.race_id = r.race_id AND ra.year = mn.year)
SELECT c.name, count(*) AS n
FROM dc JOIN constructors c USING (constructor_id)
GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 5;
