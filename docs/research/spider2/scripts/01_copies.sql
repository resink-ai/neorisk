-- name: orders B except E
select count(*) from (select order_id,customer_id,order_status,order_purchase_timestamp,order_approved_at,order_delivered_carrier_date,order_delivered_customer_date,order_estimated_delivery_date from olist_orders except select order_id,customer_id,order_status,order_purchase_timestamp,order_approved_at,order_delivered_carrier_date,order_delivered_customer_date,order_estimated_delivery_date from e.orders)
-- name: orders B except X
select count(*) from (select order_id,customer_id,order_status,order_purchase_timestamp,order_approved_at,order_delivered_carrier_date,order_delivered_customer_date,order_estimated_delivery_date from olist_orders except select order_id,customer_id,order_status,order_purchase_timestamp,order_approved_at,order_delivered_carrier_date,order_delivered_customer_date,order_estimated_delivery_date from x.orders)
-- name: items B except E / X
select (select count(*) from (select order_id,order_item_id,product_id,seller_id,shipping_limit_date,price,freight_value from olist_order_items except select order_id,order_item_id,product_id,seller_id,shipping_limit_date,price,freight_value from e.order_items)) e_diff,
       (select count(*) from (select order_id,order_item_id,product_id,seller_id,shipping_limit_date,price,freight_value from olist_order_items except select order_id,order_item_id,product_id,seller_id,shipping_limit_date,price,freight_value from x.order_items)) x_diff
-- name: payments B except E / X
select (select count(*) from (select order_id,payment_sequential,payment_type,payment_installments,payment_value from olist_order_payments except select order_id,payment_sequential,payment_type,payment_installments,payment_value from e.order_payments)) e_diff,
       (select count(*) from (select order_id,payment_sequential,payment_type,payment_installments,payment_value from olist_order_payments except select order_id,payment_sequential,payment_type,payment_installments,payment_value from x.order_payments)) x_diff
-- name: reviews B except E / X (NULL-safe via EXCEPT)
select (select count(*) from (select review_id,order_id,review_score,review_comment_title,review_comment_message,review_creation_date,review_answer_timestamp from olist_order_reviews except select review_id,order_id,review_score,review_comment_title,review_comment_message,review_creation_date,review_answer_timestamp from e.order_reviews)) e_diff,
       (select count(*) from (select review_id,order_id,review_score,review_comment_title,review_comment_message,review_creation_date,review_answer_timestamp from olist_order_reviews except select review_id,order_id,review_score,review_comment_title,review_comment_message,review_creation_date,review_answer_timestamp from x.order_reviews)) x_diff
-- name: customers/sellers/products/translation diffs
select (select count(*) from (select customer_id,customer_unique_id,customer_zip_code_prefix,customer_city,customer_state from olist_customers except select customer_id,customer_unique_id,customer_zip_code_prefix,customer_city,customer_state from e.customers)) cust_e,
       (select count(*) from (select customer_id,customer_unique_id,customer_zip_code_prefix,customer_city,customer_state from olist_customers except select customer_id,customer_unique_id,customer_zip_code_prefix,customer_city,customer_state from x.customers)) cust_x,
       (select count(*) from (select * from olist_sellers except select seller_id,seller_zip_code_prefix,seller_city,seller_state from e.sellers)) sel_e,
       (select count(*) from (select * from olist_sellers except select seller_id,seller_zip_code_prefix,seller_city,seller_state from x.sellers)) sel_x,
       (select count(*) from (select * from olist_products except select product_id,product_category_name,product_name_lenght,product_description_lenght,product_photos_qty,product_weight_g,product_length_cm,product_height_cm,product_width_cm from e.products)) prod_e,
       (select count(*) from (select * from olist_products except select product_id,product_category_name,product_name_lenght,product_description_lenght,product_photos_qty,product_weight_g,product_length_cm,product_height_cm,product_width_cm from x.products)) prod_x,
       (select count(*) from (select * from olist_products except select product_id,product_category_name,product_name_lenght,product_description_lenght,product_photos_qty,product_weight_g,product_length_cm,product_height_cm,product_width_cm from olist_products_dataset)) prod_vs_dataset,
       (select count(*) from (select * from product_category_name_translation except select product_category_name,product_category_name_english from e.product_category_name_translation)) tr_e,
       (select count(*) from (select * from product_category_name_translation except select product_category_name,product_category_name_english from x.product_category_name_translation)) tr_x
-- name: geolocation diffs
select (select count(*) from (select * from olist_geolocation except select geolocation_zip_code_prefix,geolocation_lat,geolocation_lng,geolocation_city,geolocation_state from e.geolocation)) geo_e,
       (select count(*) from (select * from olist_geolocation except select geolocation_zip_code_prefix,geolocation_lat,geolocation_lng,geolocation_city,geolocation_state from x.geolocation)) geo_x
-- name: X index column range per table
select 'orders', min("index"), max("index"), count(distinct "index") from x.orders union all
select 'order_items', min("index"), max("index"), count(distinct "index") from x.order_items
-- name: E row order equals B row order? (orders rowid alignment)
select count(*) from olist_orders b join e.orders o on b.rowid=o.rowid where b.order_id<>o.order_id
-- name: typeof checks (B) timestamp storage and empty strings
select typeof(order_approved_at) t, count(*) from olist_orders group by t
-- name: empty-string vs NULL in B review comments
select sum(review_comment_title is null) t_null, sum(review_comment_title='') t_empty, sum(review_comment_message is null) m_null, sum(review_comment_message='') m_empty from olist_order_reviews
-- name: empty-string vs NULL in E review comments
select sum(review_comment_title is null) t_null, sum(review_comment_title='') t_empty, sum(review_comment_message is null) m_null, sum(review_comment_message='') m_empty from e.order_reviews
-- name: empty-string vs NULL in X review comments
select sum(review_comment_title is null) t_null, sum(review_comment_title='') t_empty, sum(review_comment_message is null) m_null, sum(review_comment_message='') m_empty from x.order_reviews
-- name: orders timestamps null vs empty (B, E, X)
select 'B', sum(order_approved_at is null), sum(order_approved_at=''), sum(order_delivered_customer_date is null), sum(order_delivered_customer_date='') from olist_orders union all
select 'E', sum(order_approved_at is null), sum(order_approved_at=''), sum(order_delivered_customer_date is null), sum(order_delivered_customer_date='') from e.orders union all
select 'X', sum(order_approved_at is null), sum(order_approved_at=''), sum(order_delivered_customer_date is null), sum(order_delivered_customer_date='') from x.orders
