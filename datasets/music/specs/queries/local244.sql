-- local244: classify tracks as short, medium or long by duration (external doc
-- music_length_type.md: short below (min + avg) / 2 ms, long from (avg + max) / 2, medium
-- between); per class, the min and max duration in minutes and the total invoice-line revenue.
-- Written from the question (no gold SQL). Reproduces gold variant local244_a.csv, 3 of 3 rows
-- (lower-case class names; the revenue sums agree within float rounding).
WITH s AS (SELECT min(Milliseconds) mn, avg(Milliseconds) av, max(Milliseconds) mx FROM Track),
t AS (SELECT t.TrackId, t.Milliseconds,
             CASE WHEN t.Milliseconds < (s.mn + s.av) / 2 THEN 'short'
                  WHEN t.Milliseconds < (s.av + s.mx) / 2 THEN 'medium'
                  ELSE 'long' END AS cat
      FROM Track t, s),
r AS (SELECT TrackId, sum(UnitPrice * Quantity) rev FROM InvoiceLine GROUP BY 1)
SELECT cat AS CATEGORY, min(Milliseconds) / 60000.0 AS MIN_DURATION_MINUTES,
       max(Milliseconds) / 60000.0 AS MAX_DURATION_MINUTES, total(rev) AS TOTAL_REVENUE
FROM t LEFT JOIN r USING (TrackId) GROUP BY cat;
