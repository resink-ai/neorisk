-- Data Mart: events → source tables (refdata rebuild, DuckDB).

-- table: weekly_sales
SELECT strftime(event_time AT TIME ZONE 'UTC', '%-d/%-m/%y') AS week_date, region, platform,
       segment, customer_type, transactions, sales // 100 AS sales
FROM weekly_sales_reported;

-- table: cleaned_weekly_sales
-- The case study's step-1 cleansing. week_number is the ISO week; avg_transaction is
-- sales / transactions rounded half up to 2 dp, by integer division (round() misses ties).
SELECT strftime(ts, '%Y-%-m-%-d') AS week_date_formatted, strftime(ts, '%Y-%m-%d') AS week_date,
       region, platform, coalesce(segment, 'unknown') AS segment, customer_type, transactions,
       sales, weekofyear(ts) AS week_number, month(ts) AS month_number, year(ts) AS calendar_year,
       CASE substr(segment, 2, 1) WHEN '1' THEN 'Young Adults' WHEN '2' THEN 'Middle Aged'
            WHEN '3' THEN 'Retirees' WHEN '4' THEN 'Retirees' ELSE 'unknown' END AS age_band,
       CASE substr(segment, 1, 1) WHEN 'C' THEN 'Couples' WHEN 'F' THEN 'Families'
            ELSE 'unknown' END AS demographic,
       ((200 * sales + transactions) // (2 * transactions)) / 100.0 AS avg_transaction
FROM (SELECT event_time AT TIME ZONE 'UTC' AS ts, region, platform, segment, customer_type,
             transactions, sales // 100 AS sales
      FROM weekly_sales_reported);
