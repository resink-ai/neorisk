-- name: payment type (seq min) for canceled-before-approval vs all
select case when o.order_status='canceled' and o.order_approved_at is null then 'canceled_unapproved' when o.order_status='unavailable' then 'unavailable' when o.order_status='canceled' then 'canceled_approved' else 'other' end g, p.payment_type, count(*)
from olist_orders o join olist_order_payments p on p.order_id=o.order_id and p.payment_sequential=(select min(payment_sequential) from olist_order_payments q where q.order_id=o.order_id)
where o.order_status in ('canceled','unavailable') group by 1,2 order by 1,3 desc
-- name: unavailable/canceled orders: payment_value sum distribution (are they paid amounts?)
select order_status, count(*), round(avg(t),2) from (select o.order_status, sum(payment_value) t from olist_orders o join olist_order_payments using(order_id) where order_status in ('unavailable','canceled') group by o.order_id) group by 1
-- name: review_creation for canceled/unavailable: vs estimated date
select o.order_status, count(*), round(avg(julianday(r.review_creation_date)-julianday(o.order_estimated_delivery_date)),2) avg_days_after_est,
 sum(r.review_creation_date between date(o.order_estimated_delivery_date,'+0 day') and date(o.order_estimated_delivery_date,'+3 day')) within_0_3d
from olist_order_reviews r join olist_orders o using(order_id) where o.order_status in ('canceled','unavailable','shipped','invoiced','processing') group by 1
