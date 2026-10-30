-- order id uniqueness and order/payment/delivery id equality
select count(*) n, count(distinct order_id), sum(payment_order_id=order_id), sum(delivery_order_id=order_id), count(distinct payment_order_id), count(distinct delivery_order_id) from orders;
-- payments -> orders coverage
select count(*) pay_rows, sum(o.order_id is not null) matched, count(distinct p.payment_order_id) distinct_po from payments p left join (select distinct payment_order_id order_id from orders) o on o.order_id=p.payment_order_id;
-- orders with >=1 payment
select count(*) , sum(exists(select 1 from payments p where p.payment_order_id=o.payment_order_id)) from orders o;
-- deliveries -> orders coverage
select count(*) del_rows, sum(o.x is not null) matched, count(distinct d.delivery_order_id) from deliveries d left join (select distinct delivery_order_id x from orders) o on o.x=d.delivery_order_id;
-- orders with >=1 delivery
select count(*), sum(exists(select 1 from deliveries d where d.delivery_order_id=o.delivery_order_id)) from orders o;
-- stores->hubs
select count(*), sum(h.hub_id is not null), count(distinct s.hub_id) from stores s left join hubs h using(hub_id);
-- orders->stores, orders->channels
select count(*), sum(s.store_id is not null), (select count(*) from orders o2 left join channels c using(channel_id) where c.channel_id is null) from orders o left join stores s using(store_id);
-- deliveries->drivers
select count(*), sum(driver_id is null) null_driver, sum(driver_id is not null and driver_id not in (select driver_id from drivers)) dangling, count(distinct driver_id) from deliveries;
-- stores used / hubs used / channels used / drivers used
select (select count(distinct store_id) from orders), (select count(distinct channel_id) from orders), (select count(distinct s.hub_id) from orders o join stores s using(store_id)), (select count(*) from drivers where driver_id not in (select driver_id from deliveries where driver_id is not null));
-- delivery_id and payment_id ranges
select min(delivery_id),max(delivery_id),(select min(payment_id) from payments),(select max(payment_id) from payments),(select min(order_id) from orders),(select max(order_id) from orders) from deliveries
