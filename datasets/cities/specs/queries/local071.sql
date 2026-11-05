-- local071: June 2022: the countries whose longest streak of consecutive insert dates is the
-- longest of all; their 2-letter codes.
-- No gold SQL (gold is local071_a.csv and _b.csv). Written from the question; reproduces
-- variant _a (lowercase codes). _b is the same codes in uppercase.
WITH d AS (
    SELECT DISTINCT country_code_2 AS cc, insert_date AS dt
    FROM cities
    WHERE insert_date BETWEEN '2022-06-01' AND '2022-06-30'
),
i AS (
    SELECT cc, dt, julianday(dt) - row_number() OVER (PARTITION BY cc ORDER BY dt) AS grp
    FROM d
),
s AS (SELECT cc, count(*) AS len FROM i GROUP BY cc, grp),
b AS (SELECT cc, max(len) AS best FROM s GROUP BY cc)
SELECT cc AS country_code_2
FROM b
WHERE best = (SELECT max(best) FROM b)
ORDER BY cc;
