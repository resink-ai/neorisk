-- order_status counts
select order_status, count(*) from orders group by 1;
-- nulls per moment by status (count non-null)
select order_status, count(*) n, count(order_moment_created) cr, count(order_moment_accepted) acc, count(order_moment_ready) rdy, count(order_moment_collected) col, count(order_moment_in_expedition) exp, count(order_moment_delivering) dlv, count(order_moment_delivered) dld, count(order_moment_finished) fin from orders group by 1;
-- metric non-null by status
select order_status, count(order_metric_collected_time), count(order_metric_paused_time), count(order_metric_production_time), count(order_metric_walking_time), count(order_metric_expediton_speed_time), count(order_metric_transit_time), count(order_metric_cycle_time) from orders group by 1;
-- null patterns of moments (bitmask) top
select order_status, (order_moment_accepted is not null)||(order_moment_ready is not null)||(order_moment_collected is not null)||(order_moment_in_expedition is not null)||(order_moment_delivering is not null)||(order_moment_delivered is not null)||(order_moment_finished is not null) pat, count(*) from orders group by 1,2 order by 3 desc limit 30;
-- empty strings?
select sum(order_moment_accepted=''), sum(order_metric_cycle_time=''), sum(typeof(order_metric_cycle_time)='text'), sum(typeof(order_moment_created)) from orders;
-- typeof per column
select typeof(order_amount), typeof(order_delivery_fee), typeof(order_delivery_cost), typeof(order_metric_cycle_time), count(*) from orders group by 1,2,3,4;
-- delivery_status counts
select delivery_status, count(*), sum(driver_id is null), avg(delivery_distance_meters) from deliveries group by 1;
-- payment_status/method
select payment_status, payment_method, count(*), round(sum(payment_amount),2), round(avg(payment_fee),3) from payments group by 1,2 order by 3 desc;
-- channels
select channel_type, count(*) from channels group by 1;
-- drivers
select driver_modal, driver_type, count(*) from drivers group by 1,2;
-- stores segment / plan price
select store_segment, store_plan_price, count(*) from stores group by 1,2 order by 3 desc limit 20;
-- stores with null coords
select sum(store_latitude is null), sum(store_name is null), count(distinct store_name) from stores;
-- hubs by state/city
select hub_state, hub_city, count(*) from hubs group by 1,2
