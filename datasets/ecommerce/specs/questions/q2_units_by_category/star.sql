SELECT s.category, CAST(count(*) AS BIGINT) AS lines, CAST(sum(f.quantity) AS BIGINT) AS units,
       CAST(sum(f.amount) AS BIGINT) AS amount
FROM star_fact_order_lines f JOIN star_dim_skus s USING (sku_id)
GROUP BY s.category;
