-- local277: the average forecast 2018 annual sales of products 4160 and 7790. Monthly sales
-- from 2016-01 are time steps t = 1..36. The CMA (external doc calculation_method.md) is the
-- mean of the 12-month windows t-5..t+6 and t-6..t+5, for t = 7..30. A month-of-year's
-- seasonality is the mean sales/CMA ratio of its steps in 7..30. A least-squares line is fitted
-- to the deseasonalized sales of steps 7..30 (months of seasonality 0 left out); the forecast of
-- each 2018 step (25..36) is that line times its seasonality, summed per product.
-- Written from the question (no gold SQL); no gold variant is reproduced. This reading gives
-- 375.32; the three golds disagree with each other (277.33, 266.22, 417.45).
WITH s AS (SELECT product_id, qty,
                  row_number() OVER (PARTITION BY product_id ORDER BY mth) AS t
           FROM monthly_sales WHERE product_id IN (4160, 7790) AND mth >= '2016-01-01'),
c AS (SELECT a.product_id, a.t, a.qty,
             ((SELECT avg(qty) FROM s b WHERE b.product_id = a.product_id
               AND b.t BETWEEN a.t - 5 AND a.t + 6) +
              (SELECT avg(qty) FROM s b WHERE b.product_id = a.product_id
               AND b.t BETWEEN a.t - 6 AND a.t + 5)) / 2 AS cma
      FROM s a WHERE a.t BETWEEN 7 AND 30),
seas AS (SELECT product_id, (t - 1) % 12 AS m, avg(qty / cma) AS f FROM c GROUP BY 1, 2),
d AS (SELECT c.product_id, c.t, c.qty / seas.f AS y
      FROM c JOIN seas ON seas.product_id = c.product_id AND seas.m = (c.t - 1) % 12
      WHERE seas.f > 0),
mean AS (SELECT product_id, avg(t) AS mx, avg(y) AS my FROM d GROUP BY 1),
fit AS (SELECT d.product_id,
               sum((d.t - mean.mx) * (d.y - mean.my)) / sum((d.t - mean.mx) * (d.t - mean.mx))
                 AS slope, mean.mx, mean.my
        FROM d JOIN mean USING (product_id) GROUP BY d.product_id),
yr AS (SELECT s.product_id,
              sum((fit.my + fit.slope * (s.t - fit.mx)) * seas.f) AS forecast
       FROM s JOIN fit USING (product_id)
       JOIN seas ON seas.product_id = s.product_id AND seas.m = (s.t - 1) % 12
       WHERE s.t BETWEEN 25 AND 36 GROUP BY s.product_id)
SELECT avg(forecast) AS AVG_FORECASTED_ANNUAL_SALES_2018 FROM yr;
