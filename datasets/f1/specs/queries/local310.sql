-- local310: the three years with the smallest (highest driver total + highest constructor
-- total), both summed from `results` only, in ascending order of that sum.
-- No gold SQL; written from the question. It reproduces exec_result variant local310_a
-- (1966, 1964, 1962), as docs/research/spider2/scripts/f1/p9_gold.py shows.
WITH dp AS (
    SELECT ra.year, r.driver_id, sum(r.points) AS p
    FROM results r JOIN races ra USING (race_id) GROUP BY 1, 2),
cp AS (
    SELECT ra.year, r.constructor_id, sum(r.points) AS p
    FROM results r JOIN races ra USING (race_id) GROUP BY 1, 2),
y AS (
    SELECT s.year, (SELECT max(p) FROM dp WHERE dp.year = s.year)
                   + (SELECT max(p) FROM cp WHERE cp.year = s.year) AS t
    FROM seasons s)
SELECT year FROM y WHERE t IS NOT NULL ORDER BY t, year LIMIT 3;
