-- name: key uniqueness
select 'customers.customer_id' k, count(*) n, count(distinct customer_id) d from olist_customers union all
select 'customers.customer_unique_id', count(*), count(distinct customer_unique_id) from olist_customers union all
select 'sellers.seller_id', count(*), count(distinct seller_id) from olist_sellers union all
select 'orders.order_id', count(*), count(distinct order_id) from olist_orders union all
select 'orders.customer_id', count(*), count(distinct customer_id) from olist_orders union all
select 'items.(order_id,order_item_id)', count(*), count(distinct order_id||'#'||order_item_id) from olist_order_items union all
select 'items.order_id', count(*), count(distinct order_id) from olist_order_items union all
select 'payments.(order_id,payment_sequential)', count(*), count(distinct order_id||'#'||payment_sequential) from olist_order_payments union all
select 'payments.order_id', count(*), count(distinct order_id) from olist_order_payments union all
select 'reviews.review_id', count(*), count(distinct review_id) from olist_order_reviews union all
select 'reviews.(review_id,order_id)', count(*), count(distinct review_id||'#'||order_id) from olist_order_reviews union all
select 'reviews.order_id', count(*), count(distinct order_id) from olist_order_reviews union all
select 'products.product_id', count(*), count(distinct product_id) from olist_products union all
select 'translation.product_category_name', count(*), count(distinct product_category_name) from product_category_name_translation union all
select 'geolocation.zip_prefix', count(*), count(distinct geolocation_zip_code_prefix) from olist_geolocation union all
select 'geolocation full-row distinct', count(*), (select count(*) from (select distinct * from olist_geolocation)) from olist_geolocation union all
select 'leads_qualified.mql_id', count(*), count(distinct mql_id) from e.leads_qualified union all
select 'leads_closed.mql_id', count(*), count(distinct mql_id) from e.leads_closed union all
select 'leads_closed.seller_id', count(*), count(distinct seller_id) from e.leads_closed
-- name: join coverage (child rows whose FK finds a parent)
select 'orders.customer_id -> customers' j, count(*) n, sum(customer_id in (select customer_id from olist_customers)) hit from olist_orders union all
select 'customers.customer_id -> orders', count(*), sum(customer_id in (select customer_id from olist_orders)) from olist_customers union all
select 'items.order_id -> orders', count(*), sum(order_id in (select order_id from olist_orders)) from olist_order_items union all
select 'items.product_id -> products', count(*), sum(product_id in (select product_id from olist_products)) from olist_order_items union all
select 'items.seller_id -> sellers', count(*), sum(seller_id in (select seller_id from olist_sellers)) from olist_order_items union all
select 'payments.order_id -> orders', count(*), sum(order_id in (select order_id from olist_orders)) from olist_order_payments union all
select 'reviews.order_id -> orders', count(*), sum(order_id in (select order_id from olist_orders)) from olist_order_reviews union all
select 'products.category -> translation (non-null)', sum(product_category_name is not null), sum(product_category_name in (select product_category_name from product_category_name_translation)) from olist_products union all
select 'customers.zip -> geolocation', count(*), sum(customer_zip_code_prefix in (select geolocation_zip_code_prefix from olist_geolocation)) from olist_customers union all
select 'sellers.zip -> geolocation', count(*), sum(seller_zip_code_prefix in (select geolocation_zip_code_prefix from olist_geolocation)) from olist_sellers union all
select 'leads_closed.mql_id -> leads_qualified', count(*), sum(mql_id in (select mql_id from e.leads_qualified)) from e.leads_closed union all
select 'leads_closed.seller_id -> sellers', count(*), sum(seller_id in (select seller_id from olist_sellers)) from e.leads_closed union all
select 'leads_closed.seller_id -> items.seller_id (sold anything)', count(*), sum(seller_id in (select seller_id from olist_order_items)) from e.leads_closed
-- name: parents with no children
select 'orders without items' w, count(*) from olist_orders where order_id not in (select order_id from olist_order_items) union all
select 'orders without payments', count(*) from olist_orders where order_id not in (select order_id from olist_order_payments) union all
select 'orders without reviews', count(*) from olist_orders where order_id not in (select order_id from olist_order_reviews) union all
select 'products never sold', count(*) from olist_products where product_id not in (select product_id from olist_order_items) union all
select 'sellers never sold', count(*) from olist_sellers where seller_id not in (select seller_id from olist_order_items) union all
select 'categories in products missing from translation', count(distinct product_category_name) from olist_products where product_category_name not in (select product_category_name from product_category_name_translation) union all
select 'translation categories unused by products', count(*) from product_category_name_translation where product_category_name not in (select product_category_name from olist_products where product_category_name is not null)
-- name: categories missing translation (names)
select product_category_name, count(*) from olist_products where product_category_name not in (select product_category_name from product_category_name_translation) group by 1
-- name: orders without items by status
select order_status, count(*) from olist_orders where order_id not in (select order_id from olist_order_items) group by 1 order by 2 desc
-- name: order without payments (detail)
select o.order_id, order_status, order_purchase_timestamp from olist_orders o where order_id not in (select order_id from olist_order_payments)
-- name: customer_id per customer_unique_id, orders per customer_id
select max(c) max_orders_per_customer_id from (select customer_id, count(*) c from olist_orders group by 1)
