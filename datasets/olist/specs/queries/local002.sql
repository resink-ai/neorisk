-- local002: linear regression of daily toy sales (2017-01-01..2018-08-29), predicted for
-- 2018-12-03..12-10; the sum of the 5-day symmetric moving averages for Dec 5..8.
-- Written from the question (no gold SQL); E_commerce names.
WITH daily AS (
  SELECT date(o.order_purchase_timestamp) AS d, SUM(i.price) AS sales
  FROM orders o JOIN order_items i USING (order_id)
  JOIN products p USING (product_id)
  JOIN product_category_name_translation t USING (product_category_name)
  WHERE t.product_category_name_english = 'toys'
    AND date(o.order_purchase_timestamp) BETWEEN '2017-01-01' AND '2018-08-29'
  GROUP BY 1),
xy AS (SELECT julianday(d) - julianday('2017-01-01') AS x, sales AS y FROM daily),
fit AS (SELECT (COUNT(*) * SUM(x * y) - SUM(x) * SUM(y))
               / (COUNT(*) * SUM(x * x) - SUM(x) * SUM(x)) AS b,
               AVG(y) AS my, AVG(x) AS mx FROM xy),
pred AS (SELECT julianday('2018-12-03') - julianday('2017-01-01') + k AS x, k
         FROM (SELECT 0 AS k UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3
               UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7)),
yhat AS (SELECT k, my + b * (x - mx) AS y FROM pred, fit),
sma AS (SELECT k, AVG(y) OVER (ORDER BY k ROWS BETWEEN 2 PRECEDING AND 2 FOLLOWING) AS m
        FROM yhat)
SELECT ROUND(SUM(m), 4) AS total FROM sma WHERE k BETWEEN 2 AND 5;
