-- delivered moment presence by month and channel type
select o.order_created_month, round(avg(order_moment_delivered is not null),4), round(avg(order_moment_in_expedition is null),4) from orders o where order_status='FINISHED' group by 1;
-- delivered moment presence by top channels
select channel_id, count(*), round(avg(order_moment_delivered is not null),4) from orders where order_status='FINISHED' group by 1 order by 2 desc limit 6;
-- hubs per driver
select k, count(*) from (select d.driver_id, count(distinct s.hub_id) k from deliveries d join orders o on o.order_id=d.delivery_order_id join stores s using(store_id) where d.driver_id is not null group by 1) group by 1 order by 1 limit 8;
-- share of driver deliveries within driver's main hub
with x as (select d.driver_id, s.hub_id, count(*) c from deliveries d join orders o on o.order_id=d.delivery_order_id join stores s using(store_id) where d.driver_id is not null group by 1,2)
select sum(m)*1.0/sum(t) from (select driver_id, max(c) m, sum(c) t from x group by 1);
-- canceled orders with any delivery / payments
select sum(exists(select 1 from deliveries d where d.delivery_order_id=o.order_id)), sum(exists(select 1 from payments p where p.payment_order_id=o.order_id)), count(*) from orders o where order_status='CANCELED';
-- canceled orders: accepted share, by segment
select s.store_segment, count(*), round(avg(order_moment_accepted is not null),3) from orders o join stores s using(store_id) where order_status='CANCELED' group by 1;
-- FINISHED with null finished moment
select count(*) from orders where order_status='FINISHED' and order_moment_finished is null;
-- concurrent deliveries same driver same delivering minute (batching)
select count(*), sum(c>1) from (select d.driver_id, o.order_moment_delivering, count(*) c from deliveries d join orders o on o.order_id=d.delivery_order_id where d.driver_id is not null and o.order_moment_delivering is not null group by 1,2)
