-- local098: actors (cast PIDs) with no four-year span in their career without a film, i.e.
-- whose consecutive distinct credit years never differ by more than 4.
-- Written from the question (no gold SQL). Reproduces gold variant local098_c.csv (28698);
-- local098_a (29066) and local098_b (29065) were not reproduced.
WITH cy AS (SELECT DISTINCT trim(c.PID) AS a, CAST(substr(m.year, -4) AS INTEGER) AS y
            FROM M_Cast c JOIN Movie m USING (MID) WHERE c.PID IS NOT NULL),
g AS (SELECT a, y - lag(y) OVER (PARTITION BY a ORDER BY y) AS gap FROM cy),
mx AS (SELECT a, max(gap) AS mx FROM g GROUP BY a)
SELECT count(*) AS actors_no_gap_gt3 FROM mx WHERE mx IS NULL OR mx <= 4;
