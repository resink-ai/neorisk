-- local077: for 09-2018 to 08-2019, each month's interest with the highest composition /
-- index_value, that value, its 3-month rolling average, and the top interest and value 1 and 2
-- months back.
-- No gold SQL: written from the question text. It reproduces local077_b.csv (month_year
-- verbatim; _a and _c differ only in date format and rolling-average rounding; _d blanks the
-- first two rolling averages).
WITH a AS (
    SELECT m.month_year, m._year * 100 + m._month AS ym, p.interest_name,
           m.composition / m.index_value AS avg_comp,
           rank() OVER (PARTITION BY m.month_year
                        ORDER BY m.composition / m.index_value DESC) AS rk
    FROM interest_metrics m
    JOIN interest_map p ON p.id = m.interest_id
    WHERE m.month_year IS NOT NULL AND m._year * 100 + m._month BETWEEN 201809 AND 201908
),
t AS (SELECT month_year, ym, interest_name, avg_comp FROM a WHERE rk = 1)
SELECT month_year, interest_name, avg_comp AS max_index_composition,
       avg(avg_comp) OVER (ORDER BY ym ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS rolling_avg_3m,
       lag(interest_name) OVER (ORDER BY ym) AS prev1_interest_name,
       lag(avg_comp) OVER (ORDER BY ym) AS prev1_max_index_composition,
       lag(interest_name, 2) OVER (ORDER BY ym) AS prev2_interest_name,
       lag(avg_comp, 2) OVER (ORDER BY ym) AS prev2_max_index_composition
FROM t
ORDER BY ym;
