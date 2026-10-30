-- top stores share of orders
with s as (select store_id, count(*) c from orders group by 1 order by c desc) select (select sum(c) from (select c from s limit 1))*1.0/368999 top1, (select sum(c) from (select c from s limit 10))*1.0/368999 top10, (select sum(c) from (select c from s limit 50))*1.0/368999 top50, (select sum(c) from (select c from s limit 95))*1.0/368999 top10pct, (select count(*) from s where c<10) lt10, (select count(*) from s where c=1) eq1;
-- top stores
select o.store_id, s.store_name, s.store_segment, s.hub_id, count(*) c from orders o join stores s using(store_id) group by 1 order by c desc limit 8;
-- hubs share
select h.hub_id, h.hub_name, h.hub_city, count(*) c, round(count(*)*100.0/368999,2) pct, count(distinct o.store_id) stores from orders o join stores s using(store_id) join hubs h on h.hub_id=s.hub_id group by 1 order by c desc limit 10;
-- stores per hub
select min(c), avg(c), max(c) from (select hub_id, count(*) c from stores group by 1);
-- channel share top
select c.channel_id, c.channel_name, c.channel_type, count(*) n, round(count(*)*100.0/368999,2) pct from orders o join channels c using(channel_id) group by 1 order by n desc limit 8;
-- segment share
select s.store_segment, count(*), round(avg(order_amount),2), round(avg(order_status='CANCELED'),4) from orders o join stores s using(store_id) group by 1;
-- stores per channel count per store
select k, count(*) from (select store_id, count(distinct channel_id) k from orders group by 1) group by 1 order by 1 limit 10;
-- store lat/long equal to hub lat/long?
select count(*), sum(s.store_latitude=h.hub_latitude and s.store_longitude=h.hub_longitude) eq, sum(abs(s.store_latitude-h.hub_latitude)<0.01) near from stores s join hubs h using(hub_id) where s.store_latitude is not null;
-- order_amount quantiles helper: count by bucket
select case when order_amount=0 then '0' when order_amount<25 then '<25' when order_amount<50 then '25-50' when order_amount<100 then '50-100' when order_amount<200 then '100-200' when order_amount<500 then '200-500' else '500+' end b, count(*) from orders group by 1 order by min(order_amount);
-- delivery fee values top
select order_delivery_fee, count(*) from orders group by 1 order by 2 desc limit 10;
-- delivery cost values top
select order_delivery_cost, count(*) from orders group by 1 order by 2 desc limit 10;
-- distance buckets
select case when delivery_distance_meters is null then 'null' when delivery_distance_meters=0 then '0' when delivery_distance_meters<1000 then '<1k' when delivery_distance_meters<2000 then '1-2k' when delivery_distance_meters<4000 then '2-4k' when delivery_distance_meters<8000 then '4-8k' when delivery_distance_meters<20000 then '8-20k' else '20k+' end b, count(*) from deliveries group by 1 order by min(coalesce(delivery_distance_meters,-1));
-- max distance, typeof
select max(delivery_distance_meters), min(delivery_distance_meters), sum(typeof(delivery_distance_meters)='real') from deliveries;
-- deliveries by driver modal/type share
select dr.driver_modal, dr.driver_type, count(*), round(avg(d.delivery_distance_meters)) from deliveries d join drivers dr using(driver_id) where delivery_distance_meters<100000 group by 1,2;
-- payment fee / amount ratio by method
select payment_method, count(*), round(avg(payment_amount),2), round(avg(case when payment_amount>0 then payment_fee/payment_amount end),4) fee_rate, round(avg(payment_fee=0),3) fee0 from payments group by 1 order by 2 desc
