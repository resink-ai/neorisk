-- local034: per product category, the number of payments with its most used payment type;
-- the average of those numbers over categories.
-- Written from the question (no gold SQL); E_commerce names.
WITH c AS (SELECT p.product_category_name AS cat, pay.payment_type,
                  COUNT(DISTINCT pay.order_id || '#' || pay.payment_sequential) AS n
           FROM order_items i JOIN products p USING (product_id)
           JOIN order_payments pay USING (order_id)
           GROUP BY 1, 2),
top AS (SELECT cat, MAX(n) AS n FROM c GROUP BY cat)
SELECT ROUND(AVG(n), 2) AS avg_top_payments FROM top;
