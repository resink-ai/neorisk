-- local275: products whose sales-to-CMA ratio stays above 2 in every month of 2017. Monthly
-- sales from 2016-01 as time steps t = 1..36; the centered moving average (external doc
-- calculation_method.md) is the mean of two 12-month windows, t-5..t+6 and t-6..t+5, kept
-- for t = 7..30.
-- Written from the question (no gold SQL). Reproduces gold variant local275_a.csv: no rows
-- (the best products are above 2 in 3 of 12 months).
WITH s AS (SELECT product_id, mth, qty,
                  row_number() OVER (PARTITION BY product_id ORDER BY mth) AS t
           FROM monthly_sales WHERE mth >= '2016-01-01'),
c AS (SELECT a.product_id, a.mth, a.qty,
             ((SELECT avg(qty) FROM s b WHERE b.product_id = a.product_id
               AND b.t BETWEEN a.t - 5 AND a.t + 6) +
              (SELECT avg(qty) FROM s b WHERE b.product_id = a.product_id
               AND b.t BETWEEN a.t - 6 AND a.t + 5)) / 2 AS cma
      FROM s a WHERE a.t BETWEEN 7 AND 30)
SELECT p.id AS product_id, p.name
FROM c JOIN products p ON p.id = c.product_id
WHERE c.mth LIKE '2017%'
GROUP BY p.id, p.name
HAVING min(c.qty / c.cma) > 2
ORDER BY p.id;
