-- local068: cities inserted in April, May and June of 2021-2023; each month's running total
-- across the years; year-over-year growth of both, shown for 2022 and 2023.
-- No gold SQL (gold is local068_a.csv and _b.csv). Written from the question; reproduces
-- variant _a (growth in percent, 6 decimals). _b only rounds to 2 decimals and names the months.
WITH m AS (
    SELECT CAST(strftime('%Y', insert_date) AS INTEGER) AS year,
           CAST(strftime('%m', insert_date) AS INTEGER) AS month, count(*) AS monthly_total
    FROM cities
    WHERE strftime('%Y', insert_date) BETWEEN '2021' AND '2023'
      AND strftime('%m', insert_date) IN ('04', '05', '06')
    GROUP BY 1, 2
),
r AS (
    SELECT year, month, monthly_total,
           sum(monthly_total) OVER (PARTITION BY month ORDER BY year) AS running_total
    FROM m
),
g AS (
    SELECT *, lag(monthly_total) OVER (PARTITION BY month ORDER BY year) AS prev_total,
           lag(running_total) OVER (PARTITION BY month ORDER BY year) AS prev_running
    FROM r
)
SELECT year, month, monthly_total, running_total,
       round(100.0 * (monthly_total - prev_total) / prev_total, 6) AS monthly_total_yoy_growth,
       round(100.0 * (running_total - prev_running) / prev_running, 6) AS running_total_yoy_growth
FROM g
WHERE year IN (2022, 2023)
ORDER BY year, month;
