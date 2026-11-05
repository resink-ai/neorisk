-- Vegetable wholesale: source tables → events (refdata ingest). Every REAL becomes an integer of
-- its grid: grams, jiao, fen, basis points.

-- entity: categories
-- Created at the catalog start, 2020-07-01 (a rule).
SELECT DISTINCT CAST(category_code AS TEXT) AS ext_id, category_name,
       '2020-07-01 00:00:00' AS created_at
FROM veg_cat ORDER BY category_code;

-- entity: items
-- Created at the item's first wholesale quote (a rule); the loss rate is a snapshot at N.
SELECT CAST(c.item_code AS TEXT) AS ext_id, c.item_name,
       CAST(c.category_code AS TEXT) AS category_key,
       (SELECT min(w.whsle_date) FROM veg_whsle_df w WHERE w.item_code = c.item_code) AS created_at
FROM veg_cat c ORDER BY c.item_code;

-- event: wholesale_price_quoted owner=item_key
-- At 00:00 of the quote day (a rule): before that day's first sale.
SELECT whsle_date AS event_time, CAST(item_code AS TEXT) AS item_key,
       CAST(round("whsle_px_rmb-kg" * 100) AS INTEGER) AS price
FROM veg_whsle_df ORDER BY whsle_date, item_code;

-- event: item_sold owner=item_key ord=src_index
SELECT substr(txn_date, 1, 10) || ' ' || txn_time AS event_time,
       CAST(item_code AS TEXT) AS item_key,
       CAST(round("qty_sold(kg)" * 1000) AS INTEGER) AS qty_g,
       CAST(round("unit_selling_px_rmb/kg" * 10) AS INTEGER) AS unit_price_jiao,
       "discount(%)" AS discount_pct, "index" AS src_index
FROM veg_txn_df WHERE "qty_sold(kg)" > 0 ORDER BY "index";

-- event: item_returned owner=item_key ord=src_index
SELECT substr(txn_date, 1, 10) || ' ' || txn_time AS event_time,
       CAST(item_code AS TEXT) AS item_key,
       CAST(round("qty_sold(kg)" * 1000) AS INTEGER) AS qty_g,
       CAST(round("unit_selling_px_rmb/kg" * 10) AS INTEGER) AS unit_price_jiao,
       "discount(%)" AS discount_pct, "index" AS src_index
FROM veg_txn_df WHERE "qty_sold(kg)" < 0 ORDER BY "index";

-- event: items_snapshot owner=item_key
-- At N = 2023-06-30 21:40:48, the last POS line: the loss rate is a statistic of the period.
SELECT '2023-06-30 21:40:48' AS event_time, CAST(item_code AS TEXT) AS item_key,
       CAST(round("loss_rate_%" * 100) AS INTEGER) AS loss_rate_bp
FROM veg_loss_rate_df ORDER BY item_code;
