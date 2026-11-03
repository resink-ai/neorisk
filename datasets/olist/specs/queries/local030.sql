-- local030: the five cities with the lowest summed payments over delivered orders; the
-- average of their payment totals and of their delivered-order counts.
-- Written from the question (no gold SQL); E_commerce names; ties broken by city.
WITH c AS (SELECT cu.customer_city AS city, SUM(p.payment_value) AS paid,
                  COUNT(DISTINCT o.order_id) AS n
           FROM orders o JOIN customers cu USING (customer_id)
           JOIN order_payments p USING (order_id)
           WHERE o.order_status = 'delivered' GROUP BY 1),
low AS (SELECT * FROM c ORDER BY paid, city LIMIT 5)
SELECT AVG(paid) AS avg_paid, AVG(n) AS avg_orders FROM low;
