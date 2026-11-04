-- COVID-19 by state: source table → events (refdata ingest). The distinct rows are the data; a
-- row with an identical copy at a later rowid is a Spider2 duplicate (rows 1-10), marked at
-- N = 2020-11-11 00:00:00, the last report (a rule).

-- event: daily_totals_reported owner=state
SELECT date AS event_time, state, total_cases, total_deaths
FROM (SELECT DISTINCT * FROM statistics) ORDER BY date, state;

-- event: source_row_duplicated owner=src_table ord=src_rowid
SELECT '2020-11-11 00:00:00' AS event_time, 'statistics' AS src_table, a.date, a.state,
       a.rowid AS src_rowid
FROM statistics a WHERE EXISTS (
    SELECT 1 FROM statistics b WHERE b.rowid > a.rowid AND b.date IS a.date
    AND b.state IS a.state AND b.total_cases IS a.total_cases
    AND b.total_deaths IS a.total_deaths)
ORDER BY a.rowid;
