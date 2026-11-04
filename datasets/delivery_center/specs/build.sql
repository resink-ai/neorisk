-- Delivery Center: events → source tables (refdata rebuild, DuckDB).

-- table: channels
SELECT CAST(ext_id AS BIGINT) AS channel_id, channel_name, channel_type FROM channels;

-- table: drivers
SELECT CAST(ext_id AS BIGINT) AS driver_id, driver_modal, driver_type FROM drivers;

-- table: deliveries
SELECT a.delivery_id, a.order_id AS delivery_order_id, CAST(dr.ext_id AS BIGINT) AS driver_id,
       a.delivery_distance_meters,
       COALESCE(CAST(c.delivery_status AS VARCHAR), 'DELIVERING') AS delivery_status
FROM delivery_assigned a
LEFT JOIN drivers dr USING (driver_key)
LEFT JOIN delivery_closed c USING (delivery_id);

-- table: hubs
SELECT CAST(ext_id AS BIGINT) AS hub_id, hub_name, hub_city, hub_state, hub_latitude,
       hub_longitude
FROM hubs;

-- table: payments
SELECT payment_id, order_id AS payment_order_id, CAST(payment_amount AS DOUBLE) / 100
           AS payment_amount,
       CAST(payment_fee AS DOUBLE) / 100 AS payment_fee,
       CAST(payment_method AS VARCHAR) AS payment_method,
       CAST(payment_status AS VARCHAR) AS payment_status
FROM payment_recorded;

-- table: stores
SELECT CAST(s.ext_id AS BIGINT) AS store_id, CAST(h.ext_id AS BIGINT) AS hub_id, s.store_name,
       s.store_segment, s.store_plan_price, s.store_latitude, s.store_longitude
FROM stores s JOIN hubs h USING (hub_key);

-- table: orders
WITH st AS (SELECT order_id,
                   MAX(CASE WHEN stage = 'accepted' THEN event_time END) AS accepted,
                   MAX(CASE WHEN stage = 'ready' THEN event_time END) AS ready,
                   MAX(CASE WHEN stage = 'collected' THEN event_time END) AS collected,
                   MAX(CASE WHEN stage = 'in_expedition' THEN event_time END) AS in_expedition,
                   MAX(CASE WHEN stage = 'delivering' THEN event_time END) AS delivering,
                   MAX(CASE WHEN stage = 'delivered' THEN event_time END) AS delivered,
                   MAX(CASE WHEN stage = 'finished' THEN event_time END) AS finished
            FROM order_stage GROUP BY order_id)
SELECT o.order_id, CAST(s.ext_id AS BIGINT) AS store_id, CAST(ch.ext_id AS BIGINT) AS channel_id,
       o.order_id AS payment_order_id, o.order_id AS delivery_order_id,
       CAST(c.order_status AS VARCHAR) AS order_status,
       CAST(o.order_amount AS DOUBLE) / 100 AS order_amount,
       CAST(o.order_delivery_fee AS DOUBLE) / 100 AS order_delivery_fee,
       CAST(c.order_delivery_cost AS DOUBLE) / 100 AS order_delivery_cost,
       o.order_created_hour, o.order_created_minute, o.order_created_day,
       o.order_created_month, o.order_created_year,
       strftime(o.event_time AT TIME ZONE 'UTC', '%-m/%-d/%Y %-I:%M:%S %p') AS order_moment_created,
       strftime(st.accepted AT TIME ZONE 'UTC', '%-m/%-d/%Y %-I:%M:%S %p') AS order_moment_accepted,
       strftime(st.ready AT TIME ZONE 'UTC', '%-m/%-d/%Y %-I:%M:%S %p') AS order_moment_ready,
       strftime(st.collected AT TIME ZONE 'UTC', '%-m/%-d/%Y %-I:%M:%S %p')
           AS order_moment_collected,
       strftime(st.in_expedition AT TIME ZONE 'UTC', '%-m/%-d/%Y %-I:%M:%S %p')
           AS order_moment_in_expedition,
       strftime(st.delivering AT TIME ZONE 'UTC', '%-m/%-d/%Y %-I:%M:%S %p')
           AS order_moment_delivering,
       strftime(st.delivered AT TIME ZONE 'UTC', '%-m/%-d/%Y %-I:%M:%S %p')
           AS order_moment_delivered,
       strftime(st.finished AT TIME ZONE 'UTC', '%-m/%-d/%Y %-I:%M:%S %p') AS order_moment_finished,
       c.order_metric_collected_time, c.order_metric_paused_time,
       c.order_metric_production_time, c.order_metric_walking_time,
       c.order_metric_expediton_speed_time, c.order_metric_transit_time,
       c.order_metric_cycle_time
FROM order_created o
JOIN stores s USING (store_key)
JOIN channels ch USING (channel_key)
JOIN order_closed c USING (order_id)
LEFT JOIN st USING (order_id);
