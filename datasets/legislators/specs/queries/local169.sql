-- local169: yearly retention, years 1-20, of the legislators whose first term starts 1917-1999
-- (retained = serving on Dec 31 of first-start year + k).
-- No gold SQL; written from the question (docs/research/spider2/legislators.md §0.1,
-- scripts/legislators/q2_gold.sql local169_all_dec31). Reproduces both gold CSVs, _a (percent)
-- and _b (the same numbers as a fraction): every Dec 31, not only the date dim's.
WITH f AS (SELECT id_bioguide, min(term_start) AS fs FROM legislators_terms GROUP BY 1),
c AS (SELECT * FROM f WHERE fs BETWEEN '1917-01-01' AND '1999-12-31'),
y(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM y WHERE n < 20),
r AS (SELECT DISTINCT c.id_bioguide, y.n AS period
      FROM c CROSS JOIN y JOIN legislators_terms t USING (id_bioguide)
      WHERE (CAST(strftime('%Y', c.fs) AS INTEGER) + y.n) || '-12-31'
            BETWEEN t.term_start AND t.term_end)
SELECT y.n AS year_after_first_term, (SELECT count(*) FROM c) AS total_cohort,
       count(r.id_bioguide) AS legislators_retained,
       round(100.0 * count(r.id_bioguide) / (SELECT count(*) FROM c), 2) AS retention_rate_percent
FROM y LEFT JOIN r ON r.period = y.n
GROUP BY y.n
ORDER BY y.n;
