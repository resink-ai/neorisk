-- local309: each year's top driver (full name) and top constructor by points.
-- The published gold SQL (results sums, bare columns under GROUP BY) matches none of the three
-- exec_result CSVs, so this is written from the question. It reproduces variant local309_a
-- exactly: the official champions, from the final driver_standings and constructor_standings,
-- with results sums for the constructors of 1950-1957, which have no constructor standings
-- (docs/research/spider2/scripts/f1/p9_gold.py).
WITH dfin AS (
    SELECT ra.year, d.driver_id, d.points
    FROM driver_standings d JOIN races ra USING (race_id)
    WHERE ra.round = (SELECT max(r2.round) FROM races r2 JOIN driver_standings x USING (race_id)
                      WHERE r2.year = ra.year)),
cfin AS (
    SELECT ra.year, c.constructor_id, c.points
    FROM constructor_standings c JOIN races ra USING (race_id)
    WHERE ra.round = (SELECT max(r2.round) FROM races r2
                      JOIN constructor_standings x USING (race_id) WHERE r2.year = ra.year)),
cp AS (
    SELECT ra.year, r.constructor_id, sum(r.points) AS p
    FROM results r JOIN races ra USING (race_id) GROUP BY 1, 2),
bd AS (
    SELECT year, driver_id FROM dfin d
    WHERE points = (SELECT max(points) FROM dfin d2 WHERE d2.year = d.year)),
bc AS (
    SELECT year, constructor_id FROM cfin c
    WHERE points = (SELECT max(points) FROM cfin c2 WHERE c2.year = c.year)
    UNION ALL
    SELECT year, constructor_id FROM cp c
    WHERE year NOT IN (SELECT year FROM cfin)
      AND p = (SELECT max(p) FROM cp c2 WHERE c2.year = c.year))
SELECT bd.year, dr.forename || ' ' || dr.surname AS driver, c.name AS constructor
FROM bd JOIN bc USING (year) JOIN drivers dr USING (driver_id)
JOIN constructors c USING (constructor_id)
ORDER BY 1, 2, 3;
