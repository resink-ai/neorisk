-- local285: per category and year 2020-2023, wholesale price stats, totals, loss and profit, 2 dp.
-- Written from the question (no gold SQL); matches gold CSV _b. Prices (avg, max, min, diff)
-- come from veg_whsle_df alone; the totals are over sale rows (returns excluded) joined to that
-- day's wholesale price and the item's loss rate; selling applies discount(%) as a percentage
-- (always 1, so x 0.99); the loss rate is averaged over the distinct items sold that year.
WITH p AS (SELECT c.category_name, CAST(substr(w.whsle_date, 1, 4) AS INTEGER) AS year,
                  avg(w."whsle_px_rmb-kg") AS avg_p, max(w."whsle_px_rmb-kg") AS max_p,
                  min(w."whsle_px_rmb-kg") AS min_p
           FROM veg_whsle_df w JOIN veg_cat c USING (item_code) GROUP BY 1, 2),
 t AS (SELECT c.category_name, CAST(substr(t.txn_date, 1, 4) AS INTEGER) AS year,
              sum(t."qty_sold(kg)" * w."whsle_px_rmb-kg") AS whole,
              sum(t."qty_sold(kg)" * t."unit_selling_px_rmb/kg"
                  * (1 - t."discount(%)" / 100.0)) AS sell,
              sum(t."qty_sold(kg)" * w."whsle_px_rmb-kg" * l."loss_rate_%" / 100.0) AS loss
       FROM veg_txn_df t
       JOIN veg_whsle_df w ON w.whsle_date = t.txn_date AND w.item_code = t.item_code
       JOIN veg_cat c ON c.item_code = t.item_code
       JOIN veg_loss_rate_df l ON l.item_code = t.item_code
       WHERE t."sale/return" = 'sale' GROUP BY 1, 2),
 r AS (SELECT c.category_name, i.year, avg(l."loss_rate_%") AS avg_lr
       FROM (SELECT DISTINCT CAST(substr(txn_date, 1, 4) AS INTEGER) AS year, item_code
             FROM veg_txn_df) i
       JOIN veg_cat c USING (item_code) JOIN veg_loss_rate_df l USING (item_code) GROUP BY 1, 2)
SELECT p.category_name, p.year, round(p.avg_p, 2) AS avg_wholesale_price,
       round(p.max_p, 2) AS max_wholesale_price, round(p.min_p, 2) AS min_wholesale_price,
       round(p.max_p - p.min_p, 2) AS wholesale_price_difference,
       round(t.whole, 2) AS total_wholesale_price, round(t.sell, 2) AS total_selling_price,
       round(r.avg_lr, 2) AS avg_loss_rate, round(t.loss, 2) AS total_loss,
       round(t.sell - t.whole - t.loss, 2) AS profit
FROM p JOIN t USING (category_name, year) JOIN r USING (category_name, year)
WHERE p.year BETWEEN 2020 AND 2023
ORDER BY p.category_name, p.year;
