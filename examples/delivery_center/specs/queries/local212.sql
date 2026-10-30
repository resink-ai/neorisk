-- local212: the 5 drivers with the highest average deliveries per active day (the day the
-- order was created). Written from the question (no gold SQL); ties broken by driver_id.
WITH daily AS (SELECT d.driver_id, o.order_created_year AS y, o.order_created_month AS m,
                      o.order_created_day AS dd, COUNT(*) AS n
               FROM deliveries d JOIN orders o ON o.order_id = d.delivery_order_id
               WHERE d.driver_id IS NOT NULL GROUP BY 1, 2, 3, 4)
SELECT driver_id, ROUND(AVG(n), 4) AS avg_daily FROM daily GROUP BY driver_id
ORDER BY avg_daily DESC, driver_id LIMIT 5;
