-- Clique Bait: events → source tables (refdata rebuild, DuckDB).

-- table: shopping_cart_users
SELECT user_id, ext_id AS cookie_id,
       strftime(created_at AT TIME ZONE 'UTC', '%Y-%m-%d') AS start_date
FROM cookies;

-- table: shopping_cart_events
SELECT e.visit_id, c.ext_id AS cookie_id, CAST(p.ext_id AS BIGINT) AS page_id,
       CAST(k.ext_id AS BIGINT) AS event_type, e.sequence_number,
       rtrim(strftime(e.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S.%f'), '0') AS event_time
FROM page_event e
JOIN cookies c USING (cookie_key)
JOIN pages p USING (page_key)
JOIN event_kinds k USING (event_kind_key);

-- table: shopping_cart_page_hierarchy
SELECT CAST(ext_id AS BIGINT) AS page_id, page_name, product_category, product_id FROM pages;

-- table: shopping_cart_event_identifier
SELECT CAST(ext_id AS BIGINT) AS event_type, event_name FROM event_kinds;

-- table: shopping_cart_campaign_identifier
SELECT CAST(ext_id AS BIGINT) AS campaign_id, products, campaign_name, start_date, end_date
FROM campaigns;
