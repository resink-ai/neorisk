-- local279: a recursive monthly inventory model for the products with minimums. The
-- December 2018 level is the stock in inventory (lots purchased up to 2018-12-31). Each month
-- of 2019 subtracts its budgeted quantity as demand; when the ending level falls below
-- qty_minimum, qty_purchase is restocked. Per product, the 2019 month whose ending level is
-- closest to the minimum (the earliest on a tie), and that absolute difference.
-- Written from the question (no gold SQL); no gold variant is reproduced. The model is
-- underspecified: local279_a.csv (6520 2019-01-01 330.0, 6600 2019-01-01 76.0) was not matched.
WITH RECURSIVE m AS (
  SELECT product_id, mth, qty, row_number() OVER (PARTITION BY product_id ORDER BY mth) AS k
  FROM monthly_budget WHERE mth LIKE '2019%'),
start AS (
  SELECT pm.product_id, pm.qty_minimum, pm.qty_purchase,
         (SELECT total(i.qty) FROM inventory i JOIN purchases pu ON pu.id = i.purchase_id
          WHERE i.product_id = pm.product_id AND pu.purchased <= '2018-12-31') AS level
  FROM product_minimums pm),
inv(product_id, k, mth, level, qty_minimum, qty_purchase) AS (
  SELECT product_id, 0, '2018-12-01', level, qty_minimum, qty_purchase FROM start
  UNION ALL
  SELECT inv.product_id, m.k, m.mth,
         CASE WHEN inv.level - m.qty < inv.qty_minimum
              THEN inv.level - m.qty + inv.qty_purchase ELSE inv.level - m.qty END,
         inv.qty_minimum, inv.qty_purchase
  FROM inv JOIN m ON m.product_id = inv.product_id AND m.k = inv.k + 1),
r AS (SELECT product_id, mth, abs(level - qty_minimum) AS diff,
             row_number() OVER (PARTITION BY product_id
                                ORDER BY abs(level - qty_minimum), mth) AS rk
      FROM inv WHERE k > 0)
SELECT product_id, mth AS month, diff AS absolute_difference
FROM r WHERE rk = 1
ORDER BY product_id;
