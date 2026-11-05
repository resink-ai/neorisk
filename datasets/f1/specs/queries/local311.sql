-- local311: the constructors with the top 3 combined points of their best driver and the
-- team, and the years they did it.
-- No gold SQL; written from the question. It reproduces variant local311_a (Red Bull 2023,
-- Red Bull 2022, Mercedes 2019): the team's final constructor standings points plus its best
-- driver's season points for it, sprints included (docs/research/spider2/scripts/f1/p9_gold.py).
WITH fin AS (
    SELECT ra.year, max(ra.round) AS r
    FROM races ra JOIN constructor_standings USING (race_id) GROUP BY 1),
cs AS (
    SELECT ra.year, cs.constructor_id, cs.points
    FROM constructor_standings cs JOIN races ra USING (race_id)
    JOIN fin ON fin.year = ra.year AND fin.r = ra.round),
dp AS (
    SELECT ra.year, r.constructor_id, r.driver_id, sum(r.points) AS p
    FROM (SELECT race_id, driver_id, constructor_id, points FROM results
          UNION ALL
          SELECT race_id, driver_id, constructor_id, points FROM sprint_results) r
    JOIN races ra USING (race_id) GROUP BY 1, 2, 3),
best AS (SELECT year, constructor_id, max(p) AS p FROM dp GROUP BY 1, 2)
SELECT c.name, cs.year
FROM cs JOIN best USING (year, constructor_id) JOIN constructors c USING (constructor_id)
ORDER BY cs.points + best.p DESC, cs.year, c.name
LIMIT 3;
