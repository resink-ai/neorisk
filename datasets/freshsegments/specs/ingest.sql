-- Fresh Segments: source tables → events (refdata ingest). Stamps are read as UTC.

-- entity: interests
SELECT CAST(id AS TEXT) AS ext_id, interest_name, interest_summary, created_at
FROM interest_map ORDER BY id;

-- event: interest_modified owner=interest_key
SELECT last_modified AS event_time, CAST(id AS TEXT) AS interest_key
FROM interest_map WHERE last_modified > created_at ORDER BY id;

-- event: interest_metrics_reported owner=interest ord=ranking
-- At the month's close (the first of the next month); month-less rows at N = 2019-09-01.
-- The source ranking orders a month's reports (it is derived, so it is not in the payload).
SELECT coalesce(date(substr(month_year, 4, 4) || '-' || substr(month_year, 1, 2) || '-01',
                     '+1 month'), '2019-09-01') || ' 00:00:00' AS event_time,
       coalesce(CAST(CAST(interest_id AS INTEGER) AS TEXT), 'none') AS interest,
       CAST(CAST(interest_id AS INTEGER) AS TEXT) AS interest_key, month_year, composition,
       index_value, ranking
FROM interest_metrics
ORDER BY event_time, ranking, rowid;
