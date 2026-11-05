-- local301: % change in sales, the 4 weeks before vs the 4 weeks after June 15, 2018 to 2020.
-- Gold SQL from xlang-ai/Spider2 spider2-lite/evaluation_suite/gold/sql/local301.sql, verbatim.
-- It reproduces local301_a.csv; the _b and _c variants do not follow this SQL.
SELECT
    before_effect,
    after_effect,
    after_effect - before_effect AS change_amount,
    ROUND(((after_effect * 1.0 / before_effect) - 1) * 100, 2) AS percent_change,
    '2018' AS year
FROM (
    SELECT
        SUM(CASE WHEN delta_weeks BETWEEN 1 AND 4 THEN sales END) AS after_effect,
        SUM(CASE WHEN delta_weeks BETWEEN -3 AND 0 THEN sales END) AS before_effect
    FROM (
        SELECT
            week_date,
            ROUND((JULIANDAY(week_date) - JULIANDAY('2018-06-15')) / 7.0) + 1 AS delta_weeks,
            sales
        FROM cleaned_weekly_sales
    ) add_delta_weeks
) AS add_before_after
UNION ALL
SELECT
    before_effect,
    after_effect,
    after_effect - before_effect AS change_amount,
    ROUND(((after_effect * 1.0 / before_effect) - 1) * 100, 2) AS percent_change,
    '2019' AS year
FROM (
    SELECT
        SUM(CASE WHEN delta_weeks BETWEEN 1 AND 4 THEN sales END) AS after_effect,
        SUM(CASE WHEN delta_weeks BETWEEN -3 AND 0 THEN sales END) AS before_effect
    FROM (
        SELECT
            week_date,
            ROUND((JULIANDAY(week_date) - JULIANDAY('2019-06-15')) / 7.0) + 1 AS delta_weeks,
            sales
        FROM cleaned_weekly_sales
    ) add_delta_weeks
) AS add_before_after
UNION ALL
SELECT
    before_effect,
    after_effect,
    after_effect - before_effect AS change_amount,
    ROUND(((after_effect * 1.0 / before_effect) - 1) * 100, 2) AS percent_change,
    '2020' AS year
FROM (
    SELECT
        SUM(CASE WHEN delta_weeks BETWEEN 1 AND 4 THEN sales END) AS after_effect,
        SUM(CASE WHEN delta_weeks BETWEEN -3 AND 0 THEN sales END) AS before_effect
    FROM (
        SELECT
            week_date,
            ROUND((JULIANDAY(week_date) - JULIANDAY('2020-06-15')) / 7.0) + 1 AS delta_weeks,
            sales
        FROM cleaned_weekly_sales
    ) add_delta_weeks
) AS add_before_after
ORDER BY year;
