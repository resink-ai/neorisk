-- Olist: source tables → events (refdata ingest). Wall clock is stored as UTC; money in cents.

-- entity: sellers
SELECT seller_id AS ext_id, seller_zip_code_prefix AS zip_code_prefix, seller_city AS city,
       seller_state AS state
FROM sellers ORDER BY seller_id;

-- entity: products
SELECT product_id AS ext_id, product_category_name AS category,
       product_name_lenght AS name_length, product_description_lenght AS description_length,
       product_photos_qty AS photos_qty, product_weight_g AS weight_g,
       product_length_cm AS length_cm, product_height_cm AS height_cm,
       product_width_cm AS width_cm
FROM products ORDER BY product_id;

-- entity: geolocation
SELECT CAST(rowid AS TEXT) AS ext_id, geolocation_zip_code_prefix AS zip_code_prefix,
       geolocation_lat AS lat, geolocation_lng AS lng, geolocation_city AS city,
       geolocation_state AS state
FROM geolocation ORDER BY rowid;

-- entity: translations
SELECT product_category_name AS ext_id, product_category_name_english AS english
FROM product_category_name_translation ORDER BY product_category_name;

-- event: lead_qualified owner=mql_id
SELECT first_contact_date || ' 00:00:00' AS event_time, mql_id, landing_page_id, origin
FROM leads_qualified ORDER BY mql_id;

-- event: lead_won owner=mql_id
SELECT won_date AS event_time, mql_id, seller_id AS seller_ext_id, sdr_id, sr_id,
       business_segment, lead_type, lead_behaviour_profile, has_company, has_gtin,
       average_stock, business_type, declared_product_catalog_size, declared_monthly_revenue
FROM leads_closed ORDER BY mql_id;

-- event: order_placed owner=order_id
SELECT o.order_purchase_timestamp AS event_time, o.order_id, o.customer_id,
       c.customer_unique_id, c.customer_zip_code_prefix AS zip_code_prefix,
       c.customer_city AS city, c.customer_state AS state,
       o.order_estimated_delivery_date AS estimated_delivery
FROM orders o JOIN customers c USING (customer_id) ORDER BY o.order_id;

-- event: order_line_added owner=order_id ord=order_item_id
SELECT o.order_purchase_timestamp AS event_time, i.order_id, i.order_item_id,
       i.product_id AS product_key, i.seller_id AS seller_key,
       CAST(ROUND(i.price * 100) AS INTEGER) AS price,
       CAST(ROUND(i.freight_value * 100) AS INTEGER) AS freight_value
FROM order_items i JOIN orders o USING (order_id) ORDER BY i.order_id, i.order_item_id;

-- event: payment_recorded owner=order_id ord=payment_sequential
SELECT o.order_purchase_timestamp AS event_time, p.order_id, p.payment_sequential,
       p.payment_type, p.payment_installments,
       CAST(ROUND(p.payment_value * 100) AS INTEGER) AS payment_value
FROM order_payments p JOIN orders o USING (order_id)
ORDER BY p.order_id, p.payment_sequential;

-- event: order_approved owner=order_id
SELECT order_approved_at AS event_time, order_id FROM orders
WHERE order_approved_at IS NOT NULL ORDER BY order_id;

-- event: seller_ship_deadline_set owner=order_id
SELECT DISTINCT COALESCE(o.order_approved_at, o.order_purchase_timestamp) AS event_time,
       i.order_id, i.seller_id AS seller_key, i.shipping_limit_date
FROM order_items i JOIN orders o USING (order_id) ORDER BY i.order_id, i.seller_id;

-- event: order_handed_to_carrier owner=order_id
SELECT order_delivered_carrier_date AS event_time, order_id FROM orders
WHERE order_delivered_carrier_date IS NOT NULL ORDER BY order_id;

-- event: order_delivered owner=order_id
SELECT order_delivered_customer_date AS event_time, order_id FROM orders
WHERE order_delivered_customer_date IS NOT NULL ORDER BY order_id;

-- event: order_status_final owner=order_id
-- Only where the status differs from the one the timestamps imply; the time is the last
-- known stage (the source has none).
SELECT MAX(order_purchase_timestamp, COALESCE(order_approved_at, ''),
           COALESCE(order_delivered_carrier_date, ''),
           COALESCE(order_delivered_customer_date, '')) AS event_time,
       order_id, order_status
FROM (SELECT *, CASE WHEN order_delivered_customer_date IS NOT NULL THEN 'delivered'
                     WHEN order_delivered_carrier_date IS NOT NULL THEN 'shipped'
                     WHEN order_approved_at IS NOT NULL THEN 'approved'
                     ELSE 'created' END AS implied FROM orders)
WHERE order_status <> implied ORDER BY order_id;

-- event: review_requested owner=order_id
SELECT review_creation_date AS event_time, review_id, order_id FROM order_reviews
ORDER BY order_id, review_id;

-- event: review_answered owner=order_id
SELECT review_answer_timestamp AS event_time, review_id, order_id, review_score,
       review_comment_title, review_comment_message
FROM order_reviews ORDER BY order_id, review_id;
