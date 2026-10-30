-- payments per order distribution (orders incl. zero)
select k, count(*) from (select o.order_id, (select count(*) from payments p where p.payment_order_id=o.order_id) k from orders o) group by k order by k;
-- deliveries per order distribution
select k, count(*) from (select o.order_id, (select count(*) from deliveries d where d.delivery_order_id=o.order_id) k from orders o) group by k order by k;
-- orders w/o payment by status; w/o delivery by status
select order_status, sum(not exists(select 1 from payments p where p.payment_order_id=o.order_id)) no_pay, sum(not exists(select 1 from deliveries d where d.delivery_order_id=o.order_id)) no_del, count(*) from orders o group by 1;
-- sum(payment_amount) vs order_amount (+fee?) for orders with payments
with ps as (select payment_order_id oid, sum(payment_amount) pa, count(*) k from payments group by 1)
select o.order_status, count(*), sum(abs(pa-order_amount)<0.005) eq_amount, sum(abs(pa-order_amount-order_delivery_fee)<0.005) eq_amt_plus_fee, sum(pa>order_amount+order_delivery_fee+0.005) over_, sum(pa<order_amount-0.005) under_ from orders o join ps on ps.oid=o.order_id group by 1;
-- same, split by k
with ps as (select payment_order_id oid, sum(payment_amount) pa, count(*) k from payments group by 1)
select min(k,4) kk, count(*), round(avg(abs(pa-order_amount-order_delivery_fee)<0.005),4) eq_amt_plus_fee, round(avg(abs(pa-order_amount)<0.005),4) eq_amt from orders o join ps on ps.oid=o.order_id group by 1;
-- method combos among multi-payment orders (top)
select combo, count(*) from (select payment_order_id, group_concat(payment_method,'+') combo from (select * from payments order by payment_order_id, payment_method) group by 1 having count(*)>1) group by 1 order by 2 desc limit 12;
-- duplicate identical payment rows within order (same amount/method)
select count(*) from (select payment_order_id, payment_amount, payment_method, count(*) c from payments group by 1,2,3 having c>1);
-- payment status vs order status
select o.order_status, p.payment_status, count(*) from payments p join orders o on o.order_id=p.payment_order_id group by 1,2;
-- delivery status vs order status
select o.order_status, d.delivery_status, count(*), sum(d.driver_id is null) from deliveries d join orders o on o.order_id=d.delivery_order_id group by 1,2;
-- multi-delivery orders: status combos and same driver?
select combo, count(*) from (select delivery_order_id, group_concat(delivery_status,'+') combo from (select * from deliveries order by delivery_order_id, delivery_id) group by 1 having count(*)>1) group by 1 order by 2 desc limit 10;
select count(*) multi, sum(nd=1) one_driver, sum(nd>1) diff_drivers, sum(dist_same) same_distance from (select delivery_order_id, count(*) c, count(distinct driver_id) nd, count(distinct delivery_distance_meters)=1 dist_same from deliveries group by 1 having c>1);
-- fee/cost stats
select order_status, round(avg(order_amount),2), round(avg(order_delivery_fee),2), round(avg(order_delivery_fee=0),4), round(avg(order_delivery_cost),2), sum(order_delivery_cost is null) cost_null, sum(order_amount=0) amt0 from orders group by 1;
-- delivery cost null vs delivery existence
select (order_delivery_cost is null) cn, exists(select 1 from deliveries d where d.delivery_order_id=o.order_id) hasd, count(*) from orders o group by 1,2;
-- channel type mix of orders; channel without delivery?
select c.channel_type, count(*), round(avg(exists(select 1 from deliveries d where d.delivery_order_id=o.order_id)),4) has_del, round(avg(o.order_status='CANCELED'),4) cancel from orders o join channels c using(channel_id) group by 1
