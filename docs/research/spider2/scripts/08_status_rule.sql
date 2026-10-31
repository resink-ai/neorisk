-- name: naive status from timestamps vs actual status
with n as (select order_status s, case when order_delivered_customer_date is not null then 'delivered' when order_delivered_carrier_date is not null then 'shipped' when order_approved_at is not null then 'approved' else 'created' end d from olist_orders)
select s, d, count(*), s=d ok from n group by 1,2 order by ok, 3 desc
-- name: naive status match total
select sum(order_status = case when order_delivered_customer_date is not null then 'delivered' when order_delivered_carrier_date is not null then 'shipped' when order_approved_at is not null then 'approved' else 'created' end), count(*) from olist_orders
-- name: DST fall-back ambiguous hour (2017-02-18 23h, 2018-02-17 23h local occur twice)
select 'purchase', count(*) from olist_orders where substr(order_purchase_timestamp,1,13) in ('2017-02-18 23','2018-02-17 23') union all
select 'approved', count(*) from olist_orders where substr(order_approved_at,1,13) in ('2017-02-18 23','2018-02-17 23') union all
select 'carrier', count(*) from olist_orders where substr(order_delivered_carrier_date,1,13) in ('2017-02-18 23','2018-02-17 23') union all
select 'customer', count(*) from olist_orders where substr(order_delivered_customer_date,1,13) in ('2017-02-18 23','2018-02-17 23') union all
select 'answer', count(*) from olist_order_reviews where substr(review_answer_timestamp,1,13) in ('2017-02-18 23','2018-02-17 23') union all
select 'shipping_limit', count(*) from olist_order_items where substr(shipping_limit_date,1,13) in ('2017-02-18 23','2018-02-17 23')
-- name: items for orders with null approved_at
select o.order_status, count(*) from olist_order_items i join olist_orders o using(order_id) where o.order_approved_at is null group by 1
-- name: review events: distinct review_ids, distinct (review_id) creation per row
select count(*), count(distinct review_id), count(distinct order_id) from olist_order_reviews
-- name: per-row event counts summary
select (select count(*) from olist_orders) placed, (select count(order_approved_at) from olist_orders) approved, (select count(order_delivered_carrier_date) from olist_orders) carrier, (select count(order_delivered_customer_date) from olist_orders) delivered,
       (select count(*) from olist_order_items) lines, (select count(*) from (select distinct order_id, seller_id from olist_order_items)) order_seller_pairs, (select count(*) from olist_order_payments) payments
