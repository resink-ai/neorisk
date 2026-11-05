-- local072: the country with inserts on exactly nine days of January 2022; its longest streak
-- of consecutive insert days that month; the share of the streak's rows that are capitals.
-- No gold SQL (gold is local072_a.csv and _b.csv). Written from the question; reproduces
-- variant _a (the share in percent, with the row counts). _b gives it as a fraction, 0.2.
WITH j AS (
    SELECT * FROM cities WHERE insert_date BETWEEN '2022-01-01' AND '2022-01-31'
),
c AS (
    SELECT country_code_2 AS cc, count(DISTINCT insert_date) AS days
    FROM j GROUP BY 1 HAVING count(DISTINCT insert_date) = 9
),
d AS (SELECT DISTINCT j.country_code_2 AS cc, j.insert_date AS dt FROM j JOIN c ON c.cc = j.country_code_2),
i AS (
    SELECT cc, dt, julianday(dt) - row_number() OVER (PARTITION BY cc ORDER BY dt) AS grp
    FROM d
),
s AS (SELECT cc, grp, min(dt) AS st, max(dt) AS en, count(*) AS len FROM i GROUP BY cc, grp),
best AS (SELECT * FROM s ORDER BY len DESC, st LIMIT 1)
SELECT best.cc AS country_code_2, c.days AS distinct_insert_days,
       best.st AS longest_streak_start_date, best.en AS longest_streak_end_date,
       best.len AS streak_length_days, count(*) AS total_rows_in_period,
       sum(j.capital) AS capital_rows_in_period,
       100.0 * sum(j.capital) / count(*) AS capital_percentage
FROM best
JOIN c ON c.cc = best.cc
JOIN j ON j.country_code_2 = best.cc AND j.insert_date BETWEEN best.st AND best.en
GROUP BY best.cc, c.days, best.st, best.en, best.len;
