SELECT c.category, CAST(count(*) AS BIGINT) AS lines, CAST(sum(q.quantity) AS BIGINT) AS units,
       CAST(sum(m.amount) AS BIGINT) AS amount
FROM an_order_lines l
JOIN an_order_lines_quantity q USING (line_id)
JOIN an_order_lines_amount m USING (line_id)
JOIN an_order_lines_for_skus k USING (line_id)
JOIN an_skus_category c USING (sku_id)
GROUP BY c.category;
