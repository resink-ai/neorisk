-- Fresh Segments: events → source tables (refdata rebuild, DuckDB).

-- table: interest_map
-- last_modified is the latest interest_modified, else created_at.
SELECT CAST(i.ext_id AS BIGINT) AS id, n.interest_name, n.interest_summary,
       strftime(i.created_at AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS created_at,
       strftime(coalesce(m.t, i.created_at) AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S')
           AS last_modified
FROM interests i LEFT JOIN interests_snapshot n USING (interest_key)
LEFT JOIN (SELECT interest_key, max(event_time) AS t FROM interest_modified
           GROUP BY interest_key) m USING (interest_key);

-- table: interest_metrics
-- ranking is RANK by index_value within month_year (the NULL month is one group);
-- percentile_ranking is 100 * (1 - ranking / rows in the group), rounded to 2 dp.
SELECT CAST(substr(r.month_year, 1, 2) AS DOUBLE) AS _month,
       CAST(substr(r.month_year, 4, 4) AS DOUBLE) AS _year, r.month_year,
       CAST(i.ext_id AS DOUBLE) AS interest_id, r.composition, r.index_value,
       rank() OVER w AS ranking,
       round(100 * (1 - rank() OVER w / count(*) OVER (PARTITION BY r.month_year)), 2)
           AS percentile_ranking
FROM interest_metrics_reported r
LEFT JOIN interests i USING (interest_key)
WINDOW w AS (PARTITION BY r.month_year ORDER BY r.index_value DESC);
