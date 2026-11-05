-- Vegetable wholesale: events → source tables (refdata rebuild, DuckDB). REALs come back from
-- their integer grids by one division; the `index` columns are sort positions.

-- table: veg_txn_df
WITH l AS (SELECT event_time, item_key, qty_g, unit_price_jiao, discount_pct, src_index
           FROM item_sold
           UNION ALL
           SELECT event_time, item_key, qty_g, unit_price_jiao, discount_pct, src_index
           FROM item_returned)
SELECT l.src_index AS "index",
       strftime(l.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') || ' 00:00:00' AS txn_date,
       strftime(l.event_time AT TIME ZONE 'UTC', '%H:%M:%S') AS txn_time,
       CAST(i.ext_id AS BIGINT) AS item_code, l.qty_g / 1000.0 AS "qty_sold(kg)",
       l.unit_price_jiao / 10.0 AS "unit_selling_px_rmb/kg",
       CASE WHEN l.qty_g > 0 THEN 'sale' ELSE 'return' END AS "sale/return",
       l.discount_pct AS "discount(%)",
       strftime(l.event_time AT TIME ZONE 'UTC', '%A') AS day_of_week
FROM l JOIN items i USING (item_key) ORDER BY l.src_index;

-- table: veg_whsle_df
SELECT row_number() OVER (ORDER BY q.event_time, CAST(i.ext_id AS BIGINT)) - 1 AS "index",
       strftime(q.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS whsle_date,
       CAST(i.ext_id AS BIGINT) AS item_code, q.price / 100.0 AS "whsle_px_rmb-kg"
FROM wholesale_price_quoted q JOIN items i USING (item_key) ORDER BY 1;

-- table: veg_cat
SELECT row_number() OVER (ORDER BY CAST(c.ext_id AS BIGINT), CAST(i.ext_id AS BIGINT)) - 1
           AS "index",
       CAST(i.ext_id AS BIGINT) AS item_code, i.item_name,
       CAST(c.ext_id AS BIGINT) AS category_code, c.category_name
FROM items i JOIN categories c USING (category_key) ORDER BY 1;

-- table: veg_loss_rate_df
SELECT row_number() OVER (ORDER BY CAST(ext_id AS BIGINT)) - 1 AS "index",
       CAST(ext_id AS BIGINT) AS item_code, item_name, loss_rate_bp / 100.0 AS "loss_rate_%"
FROM items ORDER BY 1;
