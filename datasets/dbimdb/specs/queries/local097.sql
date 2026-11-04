-- local097: the ten-year window [y, y + 9], starting at a release year present in the data,
-- that holds the most movies; its start year and count.
-- Written from the question (no gold SQL). Reproduces gold variant local097_a.csv (2008, 1205).
WITH y AS (SELECT CAST(substr(year, -4) AS INTEGER) AS y FROM Movie),
s AS (SELECT DISTINCT y FROM y)
SELECT s.y AS start_year,
       (SELECT count(*) FROM y WHERE y.y BETWEEN s.y AND s.y + 9) AS total_movies
FROM s ORDER BY total_movies DESC, start_year LIMIT 1;
