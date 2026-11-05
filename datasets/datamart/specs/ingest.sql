-- Data Mart: source tables → events (refdata ingest). week_date is d/m/yy, read as midnight UTC.
-- cleaned_weekly_sales produces no events: build.sql derives it.

-- event: weekly_sales_reported owner=region
SELECT iso_time(week_date, '%d/%m/%y') AS event_time, region, platform, segment, customer_type,
       transactions, sales * 100 AS sales
FROM weekly_sales
ORDER BY event_time, region, platform, segment, customer_type;
