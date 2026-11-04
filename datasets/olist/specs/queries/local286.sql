-- local286: sellers with more than 100 items sold: total sales, average item price, average
-- review score, average packing time (approval → carrier, hours) and the English name of
-- their top category by items. Written from the question (no gold SQL); E_commerce names
-- (the question targets electronic_sales, which holds the same rows plus an index column).
WITH items AS (SELECT i.seller_id, i.order_id, i.price, t.product_category_name_english AS cat
               FROM order_items i JOIN products p USING (product_id)
               LEFT JOIN product_category_name_translation t USING (product_category_name)),
big AS (SELECT seller_id FROM items GROUP BY seller_id HAVING COUNT(*) > 100),
topcat AS (SELECT seller_id, cat FROM (
             SELECT seller_id, cat, ROW_NUMBER() OVER (PARTITION BY seller_id
                                                      ORDER BY COUNT(*) DESC, cat) AS k
             FROM items WHERE seller_id IN (SELECT seller_id FROM big)
             GROUP BY seller_id, cat) WHERE k = 1),
rev AS (SELECT i.seller_id, AVG(r.review_score) AS score
        FROM (SELECT DISTINCT seller_id, order_id FROM items) i
        JOIN order_reviews r USING (order_id) GROUP BY 1),
pack AS (SELECT i.seller_id,
                AVG((julianday(o.order_delivered_carrier_date)
                     - julianday(o.order_approved_at)) * 24) AS hours
         FROM (SELECT DISTINCT seller_id, order_id FROM items) i JOIN orders o USING (order_id)
         WHERE o.order_delivered_carrier_date IS NOT NULL AND o.order_approved_at IS NOT NULL
         GROUP BY 1)
SELECT b.seller_id, COUNT(*) AS items, ROUND(SUM(it.price), 2) AS total_sales,
       ROUND(AVG(it.price), 2) AS avg_price, ROUND(rev.score, 2) AS avg_review,
       ROUND(pack.hours, 2) AS packing_hours, topcat.cat AS top_category
FROM big b JOIN items it USING (seller_id) LEFT JOIN rev USING (seller_id)
LEFT JOIN pack USING (seller_id) LEFT JOIN topcat USING (seller_id)
GROUP BY b.seller_id ORDER BY total_sales DESC, b.seller_id;
