SELECT s.category, CAST(count(*) AS BIGINT) AS lines, CAST(sum(d.quantity) AS BIGINT) AS units,
       CAST(sum(d.amount) AS BIGINT) AS amount
FROM dv_link_order_line l
JOIN dv_sat_order_line_details d USING (order_line_hk)
JOIN dv_sat_skus_details s USING (sku_hk)
GROUP BY s.category;
