-- local037: the top three categories by the number of payments with their most used
-- payment type, counting distinct payments (order, sequential): this reproduces the gold
-- values. Written from the question (no gold SQL); E_commerce names; ties by name.
WITH c AS (SELECT p.product_category_name AS cat, pay.payment_type,
                  COUNT(DISTINCT pay.order_id || '#' || pay.payment_sequential) AS n
           FROM order_items i JOIN products p USING (product_id)
           JOIN order_payments pay USING (order_id)
           GROUP BY 1, 2),
top AS (SELECT cat, payment_type, n,
               ROW_NUMBER() OVER (PARTITION BY cat ORDER BY n DESC, payment_type) AS k FROM c)
SELECT cat, payment_type, n FROM top WHERE k = 1 ORDER BY n DESC, cat LIMIT 3;
