-- COVID-19 by state: events → source table (refdata rebuild, DuckDB). The reported rows, then
-- one more copy of a row per source_row_duplicated marker.

-- table: statistics
WITH t AS (SELECT event_time, strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S')
                      AS date,
                  CAST(state AS VARCHAR) AS state, total_cases, total_deaths
           FROM daily_totals_reported)
SELECT date, state, total_cases, total_deaths FROM t
UNION ALL
SELECT t.date, t.state, t.total_cases, t.total_deaths
FROM source_row_duplicated d JOIN t ON t.event_time = d.date AND t.state = d.state
WHERE d.src_table = 'statistics';
