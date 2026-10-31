-- local085: employees with more than 50 orders; the top 3 by share of orders shipped on or after
-- the required date (unshipped orders count as not late).
-- Written from the question (no gold SQL); matches the gold CSV.
WITH e AS (
  SELECT employeeid, count(*) AS n, sum(shippeddate >= requireddate) AS late
  FROM orders GROUP BY 1 HAVING count(*) > 50)
SELECT employeeid, late, round(100.0 * late / n, 6) AS pct FROM e ORDER BY pct DESC LIMIT 3;
