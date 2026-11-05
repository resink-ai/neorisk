-- local302: average % change in sales, the 12 weeks before vs the 12 weeks from 2020-06-15, per
-- attribute value, averaged per attribute type; the type with the most negative average.
-- No gold SQL: written from the question text. It reproduces local302_a.csv and _b.csv
-- (demographic, -2.008666666667), which needs each value's % rounded to 3 dp before averaging.
WITH base AS (
    SELECT *, CASE WHEN week_date >= '2020-06-15' AND week_date < date('2020-06-15', '+84 days')
                   THEN 'after'
                   WHEN week_date < '2020-06-15' AND week_date >= date('2020-06-15', '-84 days')
                   THEN 'before' END AS w
    FROM cleaned_weekly_sales
    WHERE calendar_year = 2020
),
by_value AS (
    SELECT 'region' AS attr, region AS v, w, sales FROM base
    UNION ALL SELECT 'platform', platform, w, sales FROM base
    UNION ALL SELECT 'age_band', age_band, w, sales FROM base
    UNION ALL SELECT 'demographic', demographic, w, sales FROM base
    UNION ALL SELECT 'customer_type', customer_type, w, sales FROM base
),
pct AS (
    SELECT attr, v,
           round(100.0 * (sum(CASE WHEN w = 'after' THEN sales END)
                          - sum(CASE WHEN w = 'before' THEN sales END))
                 / sum(CASE WHEN w = 'before' THEN sales END), 3) AS pct_change
    FROM by_value
    GROUP BY attr, v
)
SELECT attr AS attribute_type, avg(pct_change) AS avg_pct_change
FROM pct
GROUP BY attr
ORDER BY avg_pct_change
LIMIT 1;
