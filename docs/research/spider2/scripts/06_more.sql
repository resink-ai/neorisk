-- name: review_creation < purchase: shared review_id or multi-review order?
select count(*) n, sum(r.review_id in (select review_id from olist_order_reviews group by 1 having count(*)>1)) shared_review_id,
       sum(r.order_id in (select order_id from olist_order_reviews group by 1 having count(*)>1)) multi_review_order
from olist_order_reviews r join olist_orders o using(order_id) where r.review_creation_date < o.order_purchase_timestamp
-- name: reviews whose creation < date(delivered_customer)-1: shared/multi share
select count(*) n, sum(r.review_id in (select review_id from olist_order_reviews group by 1 having count(*)>1)) shared,
       sum(r.order_id in (select order_id from olist_order_reviews group by 1 having count(*)>1)) multi
from olist_order_reviews r join olist_orders o using(order_id) where r.review_creation_date < date(o.order_delivered_customer_date,'-1 day')
-- name: multi-review orders: answer order vs creation (latest review is the 'final'?)
select count(*) from (select order_id from olist_order_reviews group by 1 having count(*)>1 and count(distinct review_answer_timestamp)<count(*))
-- name: payment seq not starting at 1: sample
select order_id, group_concat(payment_sequential||':'||payment_type||':'||payment_value, ' ') from (select * from olist_order_payments where order_id in (select order_id from olist_order_payments group by 1 having min(payment_sequential)<>1) order by order_id, payment_sequential) group by order_id limit 5
-- name: payment seq gap orders: type of rows
select payment_type, count(*) from olist_order_payments where order_id in (select order_id from olist_order_payments group by 1 having min(payment_sequential)<>1) group by 1
-- name: credit_card installments 0 rows and not_defined rows
select p.*, o.order_status from olist_order_payments p join olist_orders o using(order_id) where (payment_type='credit_card' and payment_installments=0) or payment_type='not_defined'
-- name: row order: is olist_orders stored sorted by anything?
select sum(a.order_id < b.order_id), sum(a.order_purchase_timestamp < b.order_purchase_timestamp), count(*) from olist_orders a join olist_orders b on b.rowid=a.rowid+1
-- name: row order: items stored grouped by order_id sorted?
select sum(a.order_id <= b.order_id), count(*) from olist_order_items a join olist_order_items b on b.rowid=a.rowid+1
-- name: row order: customers aligned with orders rowid?
select sum(c.customer_id=o.customer_id), count(*) from olist_customers c join olist_orders o on o.rowid=c.rowid
-- name: products_dataset index column
select min("index"), max("index"), count(*), sum(p.product_id = d.product_id) from olist_products_dataset d join olist_products p on p.rowid=d.rowid
-- name: DST spring-forward gaps (Sao Paulo: 2016-10-16, 2017-10-15, 2018-11-04 00:00-00:59 do not exist)
select 'purchase', count(*) from olist_orders where substr(order_purchase_timestamp,1,13) in ('2016-10-16 00','2017-10-15 00','2018-11-04 00') union all
select 'approved', count(*) from olist_orders where substr(order_approved_at,1,13) in ('2016-10-16 00','2017-10-15 00','2018-11-04 00') union all
select 'carrier', count(*) from olist_orders where substr(order_delivered_carrier_date,1,13) in ('2016-10-16 00','2017-10-15 00','2018-11-04 00') union all
select 'customer', count(*) from olist_orders where substr(order_delivered_customer_date,1,13) in ('2016-10-16 00','2017-10-15 00','2018-11-04 00') union all
select 'answer', count(*) from olist_order_reviews where substr(review_answer_timestamp,1,13) in ('2016-10-16 00','2017-10-15 00','2018-11-04 00') union all
select 'shipping_limit', count(*) from olist_order_items where substr(shipping_limit_date,1,13) in ('2016-10-16 00','2017-10-15 00','2018-11-04 00')
-- name: purchase counts by hour on DST-start days (sanity)
select substr(order_purchase_timestamp,1,13), count(*) from olist_orders where substr(order_purchase_timestamp,1,10) in ('2017-10-15') group by 1 limit 4
-- name: review text with newlines / CR
select sum(instr(review_comment_message, char(10))>0), sum(instr(review_comment_message, char(13))>0), max(length(review_comment_message)) from olist_order_reviews
-- name: canceled/unavailable: items presence vs stage
select order_status, (order_approved_at is not null) appr, (order_delivered_carrier_date is not null) carr, sum(order_id in (select order_id from olist_order_items)) with_items, count(*) from olist_orders where order_status in ('canceled','unavailable') group by 1,2,3
-- name: canceled with delivered_customer date (6) detail
select order_id, order_purchase_timestamp, order_approved_at, order_delivered_carrier_date, order_delivered_customer_date from olist_orders where order_status='canceled' and order_delivered_customer_date is not null
-- name: delivered with null approved: payment types
select p.payment_type, count(*) from olist_orders o join olist_order_payments p using(order_id) where o.order_status='delivered' and o.order_approved_at is null group by 1
-- name: carrier < approved by month of purchase (systematic?)
select substr(order_purchase_timestamp,1,7) m, sum(order_delivered_carrier_date < order_approved_at) n, count(*) from olist_orders where order_delivered_carrier_date is not null group by m having n>0 order by n desc limit 6
-- name: carrier < approved: approved - carrier gap (hours) distribution
select case when d<1 then '<1h' when d<24 then '1-24h' when d<24*7 then '1-7d' else '>7d' end b, count(*) from (select (julianday(order_approved_at)-julianday(order_delivered_carrier_date))*24 d from olist_orders where order_delivered_carrier_date < order_approved_at) group by b
-- name: status 'end of data' censoring: open statuses by purchase month
select substr(order_purchase_timestamp,1,7) m, order_status, count(*) from olist_orders where order_status in ('shipped','invoiced','processing','created','approved') group by 1,2 having count(*)>=20 order by 1 desc limit 15
-- name: shipped (no delivery) purchase month distribution
select substr(order_purchase_timestamp,1,4) y, count(*) from olist_orders where order_status='shipped' group by 1
-- name: customers zip with leading zero (4-digit prefixes)
select sum(customer_zip_code_prefix<10000), count(*) from olist_customers
-- name: estimated_delivery for same purchase: date-only, any orders estimated before carrier?
select sum(order_estimated_delivery_date < order_delivered_carrier_date) from olist_orders
-- name: items: same product with different sellers within an order
select count(*) from (select order_id, product_id from olist_order_items group by 1,2 having count(distinct seller_id)>1)
-- name: leads: mql with won_date earlier than first contact detail
select lq.first_contact_date, lc.won_date from e.leads_closed lc join e.leads_qualified lq using(mql_id) where lc.won_date < lq.first_contact_date
-- name: leads: won sellers present in sellers: first sale before won_date?
select sum(f < lc.won_date), count(*) from e.leads_closed lc join (select seller_id, min(o.order_purchase_timestamp) f from olist_order_items i join olist_orders o using(order_id) group by 1) s using(seller_id)
