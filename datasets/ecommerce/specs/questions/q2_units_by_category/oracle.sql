-- Order lines, units and line amount by SKU category.
SELECT s.category, CAST(count(*) AS BIGINT) AS lines, CAST(sum(l.quantity) AS BIGINT) AS units,
       CAST(sum(l.amount) AS BIGINT) AS amount
FROM sim.order_lines l JOIN sim.skus s USING (sku_id)
GROUP BY s.category;
