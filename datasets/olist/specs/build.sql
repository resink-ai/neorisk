-- Olist: events → source tables (refdata rebuild, DuckDB). Times go back to wall-clock text.

-- table: product_category_name_translation
SELECT ext_id AS product_category_name, english AS product_category_name_english
FROM translations;

-- table: sellers
SELECT x.ext_id AS seller_id, s.zip_code_prefix AS seller_zip_code_prefix,
       s.city AS seller_city, s.state AS seller_state
FROM sellers x LEFT JOIN sellers_snapshot s ON s.seller_id = x.seller_key;

-- table: customers
SELECT customer_id, customer_unique_id, zip_code_prefix AS customer_zip_code_prefix,
       city AS customer_city, state AS customer_state
FROM order_placed;

-- table: geolocation
SELECT zip_code_prefix AS geolocation_zip_code_prefix, lat AS geolocation_lat,
       lng AS geolocation_lng, city AS geolocation_city, state AS geolocation_state
FROM geolocation;

-- table: order_items
SELECT l.order_id, l.order_item_id, p.ext_id AS product_id, s.ext_id AS seller_id,
       strftime(d.shipping_limit_date AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S')
           AS shipping_limit_date,
       CAST(l.price AS DOUBLE) / 100 AS price,
       CAST(l.freight_value AS DOUBLE) / 100 AS freight_value
FROM order_line_added l
JOIN products p USING (product_key)
JOIN sellers s USING (seller_key)
JOIN seller_ship_deadline_set d ON d.order_id = l.order_id AND d.seller_key = l.seller_key;

-- table: order_payments
SELECT order_id, payment_sequential, CAST(payment_type AS VARCHAR) AS payment_type,
       payment_installments, CAST(payment_value AS DOUBLE) / 100 AS payment_value
FROM payment_recorded;

-- table: order_reviews
SELECT q.review_id, q.order_id, a.review_score, a.review_comment_title,
       a.review_comment_message,
       strftime(q.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS review_creation_date,
       strftime(a.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS review_answer_timestamp
FROM review_requested q
JOIN review_answered a ON a.review_id = q.review_id AND a.order_id = q.order_id;

-- table: orders
SELECT p.order_id, p.customer_id,
       COALESCE(CAST(f.order_status AS VARCHAR),
                CASE WHEN dl.order_id IS NOT NULL THEN 'delivered'
                     WHEN c.order_id IS NOT NULL THEN 'shipped'
                     WHEN a.order_id IS NOT NULL THEN 'approved'
                     ELSE 'created' END) AS order_status,
       strftime(p.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS order_purchase_timestamp,
       strftime(a.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS order_approved_at,
       strftime(c.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S')
           AS order_delivered_carrier_date,
       strftime(dl.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S')
           AS order_delivered_customer_date,
       strftime(p.estimated_delivery AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S')
           AS order_estimated_delivery_date
FROM order_placed p
LEFT JOIN order_approved a USING (order_id)
LEFT JOIN order_handed_to_carrier c USING (order_id)
LEFT JOIN order_delivered dl USING (order_id)
LEFT JOIN order_status_final f USING (order_id);

-- table: products
SELECT x.ext_id AS product_id, x.category AS product_category_name,
       s.name_length AS product_name_lenght, s.description_length AS product_description_lenght,
       s.photos_qty AS product_photos_qty, s.weight_g AS product_weight_g,
       s.length_cm AS product_length_cm, s.height_cm AS product_height_cm,
       s.width_cm AS product_width_cm
FROM products x LEFT JOIN products_snapshot s ON s.product_id = x.product_key;

-- table: leads_qualified
SELECT mql_id, strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS first_contact_date,
       landing_page_id, origin
FROM lead_qualified;

-- table: leads_closed
SELECT mql_id, seller_ext_id AS seller_id, sdr_id, sr_id,
       strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS won_date,
       business_segment, lead_type, lead_behaviour_profile, has_company, has_gtin,
       average_stock, business_type, declared_product_catalog_size, declared_monthly_revenue
FROM lead_won;
