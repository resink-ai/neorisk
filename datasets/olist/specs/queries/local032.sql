-- local032: among delivered orders, the sellers with the most distinct customers, the
-- highest profit (price - freight), the most distinct orders and the most 5-star ratings.
-- Written from the question (no gold SQL); E_commerce names; ties broken by seller_id.
WITH d AS (SELECT i.seller_id, i.order_id, i.price, i.freight_value, c.customer_unique_id
           FROM order_items i JOIN orders o USING (order_id) JOIN customers c USING (customer_id)
           WHERE o.order_status = 'delivered'),
a AS (SELECT 'Highest number of distinct customers' AS achievement, seller_id,
             COUNT(DISTINCT customer_unique_id) AS value FROM d GROUP BY seller_id
      ORDER BY value DESC, seller_id LIMIT 1),
b AS (SELECT 'Highest profit' AS achievement, seller_id,
             ROUND(SUM(price - freight_value), 2) AS value FROM d GROUP BY seller_id
      ORDER BY value DESC, seller_id LIMIT 1),
c AS (SELECT 'Highest number of distinct orders' AS achievement, seller_id,
             COUNT(DISTINCT order_id) AS value FROM d GROUP BY seller_id
      ORDER BY value DESC, seller_id LIMIT 1),
e AS (SELECT 'Most 5-star ratings' AS achievement, d.seller_id,
             COUNT(DISTINCT r.order_id) AS value
      FROM d JOIN order_reviews r USING (order_id) WHERE r.review_score = 5
      GROUP BY d.seller_id ORDER BY value DESC, d.seller_id LIMIT 1)
SELECT * FROM a UNION ALL SELECT * FROM b UNION ALL SELECT * FROM c UNION ALL SELECT * FROM e;
