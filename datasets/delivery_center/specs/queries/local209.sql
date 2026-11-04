-- local209: the store with the most orders, and the share of its orders that have a
-- DELIVERED delivery. Written from the question (no gold SQL); ties broken by store_id.
WITH top AS (SELECT store_id FROM orders GROUP BY store_id ORDER BY COUNT(*) DESC, store_id
             LIMIT 1)
SELECT s.store_id, s.store_name, COUNT(DISTINCT o.order_id) AS orders,
       ROUND(1.0 * COUNT(DISTINCT CASE WHEN d.delivery_status = 'DELIVERED'
                                       THEN o.order_id END)
             / COUNT(DISTINCT o.order_id), 6) AS delivered_ratio
FROM orders o JOIN stores s USING (store_id)
LEFT JOIN deliveries d ON d.delivery_order_id = o.order_id
WHERE o.store_id = (SELECT store_id FROM top)
GROUP BY s.store_id, s.store_name;
