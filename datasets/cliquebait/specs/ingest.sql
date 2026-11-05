-- Clique Bait: source tables → events (refdata ingest).

-- entity: cookies event=cookie_issued
SELECT cookie_id AS ext_id, user_id, start_date || ' 00:00:00' AS created_at
FROM shopping_cart_users ORDER BY cookie_id;

-- entity: pages
SELECT CAST(page_id AS TEXT) AS ext_id, page_name, product_category, product_id
FROM shopping_cart_page_hierarchy ORDER BY page_id;

-- entity: event_kinds
SELECT CAST(event_type AS TEXT) AS ext_id, event_name
FROM shopping_cart_event_identifier ORDER BY event_type;

-- entity: campaigns
SELECT CAST(campaign_id AS TEXT) AS ext_id, products, campaign_name, start_date, end_date
FROM shopping_cart_campaign_identifier ORDER BY campaign_id;

-- event: page_event owner=visit_id ord=sequence_number
SELECT event_time, visit_id, cookie_id AS cookie_key, page_id AS page_key,
       event_type AS event_kind_key, sequence_number
FROM shopping_cart_events ORDER BY visit_id, sequence_number;
