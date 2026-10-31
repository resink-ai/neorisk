-- name: status x timestamp null counts
select order_status, count(*) n,
  sum(order_purchase_timestamp is null) purch_null,
  sum(order_approved_at is null) appr_null,
  sum(order_delivered_carrier_date is null) carrier_null,
  sum(order_delivered_customer_date is null) cust_null,
  sum(order_estimated_delivery_date is null) est_null,
  sum(order_id in (select order_id from olist_order_items)) has_items,
  sum(order_id in (select order_id from olist_order_payments)) has_pay,
  sum(order_id in (select order_id from olist_order_reviews)) has_review
from olist_orders group by 1 order by 2 desc
-- name: timestamp formats (length) per column
select 'purchase' c, length(order_purchase_timestamp) l, count(*) from olist_orders group by l union all
select 'approved', length(order_approved_at) l, count(*) from olist_orders group by l union all
select 'carrier', length(order_delivered_carrier_date) l, count(*) from olist_orders group by l union all
select 'customer', length(order_delivered_customer_date) l, count(*) from olist_orders group by l union all
select 'estimated', length(order_estimated_delivery_date) l, count(*) from olist_orders group by l union all
select 'shipping_limit', length(shipping_limit_date) l, count(*) from olist_order_items group by l union all
select 'review_creation', length(review_creation_date) l, count(*) from olist_order_reviews group by l union all
select 'review_answer', length(review_answer_timestamp) l, count(*) from olist_order_reviews group by l union all
select 'lq.first_contact', length(first_contact_date) l, count(*) from e.leads_qualified group by l union all
select 'lc.won_date', length(won_date) l, count(*) from e.leads_closed group by l
-- name: time-of-day zero shares (date-only granularity)
select 'estimated time=00:00:00' c, sum(substr(order_estimated_delivery_date,12)='00:00:00'), count(order_estimated_delivery_date) from olist_orders union all
select 'review_creation time=00:00:00', sum(substr(review_creation_date,12)='00:00:00'), count(*) from olist_order_reviews union all
select 'carrier seconds=00', sum(substr(order_delivered_carrier_date,18,2)='00'), count(order_delivered_carrier_date) from olist_orders union all
select 'purchase seconds=00', sum(substr(order_purchase_timestamp,18,2)='00'), count(*) from olist_orders union all
select 'approved seconds=00', sum(substr(order_approved_at,18,2)='00'), count(order_approved_at) from olist_orders union all
select 'customer seconds=00', sum(substr(order_delivered_customer_date,18,2)='00'), count(order_delivered_customer_date) from olist_orders
-- name: min/max per timestamp column
select 'purchase' c, min(order_purchase_timestamp), max(order_purchase_timestamp) from olist_orders union all
select 'approved', min(order_approved_at), max(order_approved_at) from olist_orders union all
select 'carrier', min(order_delivered_carrier_date), max(order_delivered_carrier_date) from olist_orders union all
select 'customer', min(order_delivered_customer_date), max(order_delivered_customer_date) from olist_orders union all
select 'estimated', min(order_estimated_delivery_date), max(order_estimated_delivery_date) from olist_orders union all
select 'shipping_limit', min(shipping_limit_date), max(shipping_limit_date) from olist_order_items union all
select 'review_creation', min(review_creation_date), max(review_creation_date) from olist_order_reviews union all
select 'review_answer', min(review_answer_timestamp), max(review_answer_timestamp) from olist_order_reviews union all
select 'lq.first_contact', min(first_contact_date), max(first_contact_date) from e.leads_qualified union all
select 'lc.won_date', min(won_date), max(won_date) from e.leads_closed
-- name: shipping_limit_date beyond 2018-10-31
select count(*), group_concat(distinct substr(shipping_limit_date,1,10)) from olist_order_items where shipping_limit_date > '2018-10-31'
-- name: those far-future shipping_limit rows: status/purchase
select i.order_id, o.order_status, o.order_purchase_timestamp, i.shipping_limit_date from olist_order_items i join olist_orders o using(order_id) where shipping_limit_date > '2019-01-01'
-- name: orders by month (purchase) - window and thin tails
select substr(order_purchase_timestamp,1,7) m, count(*) n from olist_orders group by m order by m
-- name: out-of-order pairs (both non-null)
select 'approved < purchase' p, sum(order_approved_at < order_purchase_timestamp), count(*) from olist_orders where order_approved_at is not null union all
select 'carrier < approved', sum(order_delivered_carrier_date < order_approved_at), count(*) from olist_orders where order_delivered_carrier_date is not null and order_approved_at is not null union all
select 'carrier < purchase', sum(order_delivered_carrier_date < order_purchase_timestamp), count(*) from olist_orders where order_delivered_carrier_date is not null union all
select 'customer < carrier', sum(order_delivered_customer_date < order_delivered_carrier_date), count(*) from olist_orders where order_delivered_customer_date is not null and order_delivered_carrier_date is not null union all
select 'customer < approved', sum(order_delivered_customer_date < order_approved_at), count(*) from olist_orders where order_delivered_customer_date is not null and order_approved_at is not null union all
select 'customer < purchase', sum(order_delivered_customer_date < order_purchase_timestamp), count(*) from olist_orders where order_delivered_customer_date is not null union all
select 'estimated < purchase', sum(order_estimated_delivery_date < order_purchase_timestamp), count(*) from olist_orders union all
select 'customer > estimated (late)', sum(order_delivered_customer_date > order_estimated_delivery_date), count(*) from olist_orders where order_delivered_customer_date is not null union all
select 'shipping_limit < purchase', sum(i.shipping_limit_date < o.order_purchase_timestamp), count(*) from olist_order_items i join olist_orders o using(order_id) union all
select 'carrier > shipping_limit (seller late, per item)', sum(o.order_delivered_carrier_date > i.shipping_limit_date), count(*) from olist_order_items i join olist_orders o using(order_id) where o.order_delivered_carrier_date is not null union all
select 'review_creation < purchase', sum(r.review_creation_date < o.order_purchase_timestamp), count(*) from olist_order_reviews r join olist_orders o using(order_id) union all
select 'review_creation < delivered_customer (date)', sum(r.review_creation_date < substr(o.order_delivered_customer_date,1,10)), count(*) from olist_order_reviews r join olist_orders o using(order_id) where o.order_delivered_customer_date is not null union all
select 'review_answer < review_creation', sum(review_answer_timestamp < review_creation_date), count(*) from olist_order_reviews
-- name: delivered-before-approved etc by status
select order_status, sum(order_delivered_carrier_date < order_approved_at) carrier_lt_appr, sum(order_delivered_customer_date < order_delivered_carrier_date) cust_lt_carrier from olist_orders group by 1
-- name: status-inconsistent timestamps: delivered status with null delivered_customer; non-delivered status with delivered_customer
select order_status, sum(order_delivered_customer_date is not null) with_cust_date, sum(order_delivered_carrier_date is not null) with_carrier, sum(order_approved_at is not null) with_appr, count(*) from olist_orders group by 1
-- name: delivered orders with null fields
select sum(order_approved_at is null) appr_null, sum(order_delivered_carrier_date is null) carrier_null, sum(order_delivered_customer_date is null) cust_null from olist_orders where order_status='delivered'
-- name: status values distribution
select order_status, count(*), round(100.0*count(*)/(select count(*) from olist_orders),3) pct from olist_orders group by 1 order by 2 desc
-- name: last-known timestamp for canceled / unavailable (which stage reached)
select order_status,
 case when order_delivered_customer_date is not null then 'delivered_customer'
      when order_delivered_carrier_date is not null then 'carrier'
      when order_approved_at is not null then 'approved'
      else 'purchase_only' end stage, count(*)
from olist_orders where order_status in ('canceled','unavailable','created','invoiced','processing','shipped','approved') group by 1,2 order by 1,3 desc
-- name: reviews: orders with >1 review, reviews with >1 order
select (select count(*) from (select order_id from olist_order_reviews group by 1 having count(*)>1)) orders_multi_review,
       (select max(c) from (select count(*) c from olist_order_reviews group by order_id)) max_reviews_per_order,
       (select count(*) from (select review_id from olist_order_reviews group by 1 having count(*)>1)) review_ids_multi_order,
       (select max(c) from (select count(*) c from olist_order_reviews group by review_id)) max_orders_per_review
-- name: shared review_id: do its rows agree on score/text/dates?
select count(*) shared_ids, sum(ns=1) same_score, sum(nc=1) same_creation, sum(na=1) same_answer, sum(nm<=1) same_msg
from (select review_id, count(distinct review_score) ns, count(distinct review_creation_date) nc, count(distinct review_answer_timestamp) na, count(distinct coalesce(review_comment_message,'~')) nm from olist_order_reviews group by 1 having count(*)>1)
-- name: shared review_id: same customer_unique_id across its orders?
select count(*) shared, sum(nu=1) same_unique_customer, sum(np=1) same_purchase_ts
from (select r.review_id, count(distinct c.customer_unique_id) nu, count(distinct o.order_purchase_timestamp) np from olist_order_reviews r join olist_orders o using(order_id) join olist_customers c using(customer_id) group by 1 having count(*)>1)
-- name: orders with multiple reviews: do they differ?
select count(*) n, sum(ns>1) diff_score, sum(nc>1) diff_creation from (select order_id, count(distinct review_score) ns, count(distinct review_creation_date) nc from olist_order_reviews group by 1 having count(*)>1)
-- name: payments: orders with multiple payment rows, sequential gaps
select (select count(*) from (select order_id from olist_order_payments group by 1 having count(*)>1)) orders_multi_pay,
       (select max(c) from (select count(*) c from olist_order_payments group by order_id)) max_rows,
       (select max(payment_sequential) from olist_order_payments) max_seq,
       (select count(*) from (select order_id from olist_order_payments group by 1 having max(payment_sequential)<>count(*))) seq_gap_orders,
       (select count(*) from (select order_id from olist_order_payments group by 1 having min(payment_sequential)<>1)) seq_not_from_1
-- name: payment type values and zero/neg values
select payment_type, count(*), sum(payment_value=0) zero_val, sum(payment_installments=0) zero_inst, min(payment_value), max(payment_value) from olist_order_payments group by 1
-- name: payment total vs items total (price+freight) per order
with it as (select order_id, round(sum(price+freight_value),2) tot from olist_order_items group by 1),
     pa as (select order_id, round(sum(payment_value),2) tot from olist_order_payments group by 1)
select count(*) both_present, sum(abs(it.tot-pa.tot)<=0.01) match_1c, sum(pa.tot-it.tot>0.01) pay_gt_items, sum(it.tot-pa.tot>0.01) pay_lt_items
from it join pa using(order_id)
-- name: items: order_item_id contiguous 1..n
select count(*) orders, sum(mx=n and mn=1) contiguous from (select order_id, max(order_item_id) mx, min(order_item_id) mn, count(*) n from olist_order_items group by 1)
-- name: items: shipping_limit_date constant within order?
select count(*) orders, sum(nd=1) one_limit from (select order_id, count(distinct shipping_limit_date) nd from olist_order_items group by 1)
-- name: items: shipping_limit constant per (order,seller)?
select count(*) groups, sum(nd=1) one_limit from (select order_id, seller_id, count(distinct shipping_limit_date) nd from olist_order_items group by 1,2)
-- name: items: multi-seller orders, repeated product lines
select (select count(*) from (select order_id from olist_order_items group by 1 having count(distinct seller_id)>1)) multi_seller_orders,
       (select count(*) from (select order_id from olist_order_items group by 1 having count(distinct product_id)<count(*))) orders_with_repeated_product,
       (select count(*) from (select order_id from olist_order_items group by 1 having count(distinct product_id)=1 and count(*)>1)) orders_same_product_only
-- name: items: price/freight same across repeated product lines?
select count(*) groups, sum(np=1) same_price, sum(nf=1) same_freight from (select order_id, product_id, count(distinct price) np, count(distinct freight_value) nf from olist_order_items group by 1,2 having count(*)>1)
-- name: items: zero price/freight
select sum(price<=0) price_le0, sum(freight_value=0) freight_zero, min(price), max(price), min(freight_value), max(freight_value) from olist_order_items
-- name: customers: same customer_unique_id with different zip/city
select count(*) multi_cid_uids, sum(nz>1) diff_zip, sum(ns>1) diff_state from (select customer_unique_id, count(distinct customer_zip_code_prefix) nz, count(distinct customer_state) ns from olist_customers group by 1 having count(*)>1)
-- name: products: null attributes
select sum(product_category_name is null) cat_null, sum(product_name_lenght is null) name_len_null, sum(product_weight_g is null) w_null, sum(product_weight_g=0) w_zero, sum(product_length_cm is null) l_null from olist_products
-- name: reviews: comment presence and answer delays negative
select sum(review_comment_title is not null) has_title, sum(review_comment_message is not null) has_msg, count(*) from olist_order_reviews
-- name: geolocation: lat/lng outside Brazil bounding box
select count(*) from olist_geolocation where geolocation_lat > 5.3 or geolocation_lat < -33.8 or geolocation_lng > -34.8 or geolocation_lng < -73.99
-- name: geolocation: points per zip prefix
select min(c), avg(c), max(c) from (select count(*) c from olist_geolocation group by geolocation_zip_code_prefix)
-- name: geolocation: zips with >1 state or city spelling
select sum(ns>1) multi_state, sum(nc>1) multi_city, count(*) zips from (select geolocation_zip_code_prefix, count(distinct geolocation_state) ns, count(distinct geolocation_city) nc from olist_geolocation group by 1)
-- name: customer city vs geolocation city (exact match share)
select count(*), sum(customer_zip_code_prefix||'|'||customer_city in (select distinct geolocation_zip_code_prefix||'|'||geolocation_city from olist_geolocation)) from olist_customers c
-- name: leads: empty strings vs NULL in leads_closed
select sum(business_segment is null), sum(business_segment=''), sum(lead_behaviour_profile is null), sum(lead_behaviour_profile=''), sum(has_company is null), sum(average_stock is null), sum(average_stock=''), sum(declared_monthly_revenue is null), sum(declared_monthly_revenue=0), sum(origin is null) from e.leads_closed join e.leads_qualified using(mql_id)
-- name: leads: won_date before first_contact
select sum(lc.won_date < lq.first_contact_date), count(*) from e.leads_closed lc join e.leads_qualified lq using(mql_id)
-- name: leads: lq origin null/empty
select origin, count(*) from e.leads_qualified group by 1 order by 2 desc
