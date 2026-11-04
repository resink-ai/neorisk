-- local171: male Louisiana legislators serving on Dec 31 of each year 31-49 after their first
-- term start, by years elapsed.
-- No gold SQL; written from the question (docs/research/spider2/legislators.md §0.1,
-- scripts/legislators/q2_gold.sql local171_state_any_term). Reproduces both gold CSVs (_a, and
-- _b, which stops at 38): "Louisiana" is the state of the covering term, every Dec 31.
WITH f AS (SELECT t.id_bioguide, min(t.term_start) AS fs FROM legislators_terms t
           JOIN legislators l USING (id_bioguide)
           WHERE l.gender = 'M' GROUP BY 1),
y(n) AS (SELECT 31 UNION ALL SELECT n + 1 FROM y WHERE n < 49),
r AS (SELECT DISTINCT f.id_bioguide, y.n
      FROM f CROSS JOIN y JOIN legislators_terms t USING (id_bioguide)
      WHERE t.state = 'LA'
        AND (CAST(strftime('%Y', f.fs) AS INTEGER) + y.n) || '-12-31'
            BETWEEN t.term_start AND t.term_end)
SELECT y.n AS years_elapsed, count(r.id_bioguide) AS distinct_legislators_active
FROM y LEFT JOIN r USING (n)
GROUP BY y.n
ORDER BY y.n;
