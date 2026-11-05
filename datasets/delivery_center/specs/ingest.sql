-- Delivery Center: source tables → events (refdata ingest). Moments are parsed with
-- iso_time(text, '%m/%d/%Y %I:%M:%S %p'); money in cents. Entities are created at the first
-- order (the default). Snapshots at N = 2021-05-08 00:00, the day after the last event (a
-- finished moment of 2021-05-07 16:10:17).

-- entity: hubs
SELECT CAST(hub_id AS TEXT) AS ext_id, hub_name, hub_city, hub_state, hub_latitude,
       hub_longitude
FROM hubs ORDER BY hub_id;

-- entity: stores
SELECT CAST(store_id AS TEXT) AS ext_id, CAST(hub_id AS TEXT) AS hub_key, store_name,
       store_segment
FROM stores ORDER BY store_id;

-- entity: channels
SELECT CAST(channel_id AS TEXT) AS ext_id, channel_name, channel_type
FROM channels ORDER BY channel_id;

-- entity: drivers
SELECT CAST(driver_id AS TEXT) AS ext_id FROM drivers ORDER BY driver_id;

-- event: order_created owner=order_id
SELECT iso_time(order_moment_created, '%m/%d/%Y %I:%M:%S %p') AS event_time, order_id,
       CAST(store_id AS TEXT) AS store_key, CAST(channel_id AS TEXT) AS channel_key,
       CAST(ROUND(order_amount * 100) AS INTEGER) AS order_amount,
       CAST(ROUND(order_delivery_fee * 100) AS INTEGER) AS order_delivery_fee,
       order_created_hour, order_created_minute, order_created_day, order_created_month,
       order_created_year
FROM orders ORDER BY order_id;

-- event: order_stage owner=order_id ord=stage_no
SELECT iso_time(m, '%m/%d/%Y %I:%M:%S %p') AS event_time, order_id, stage, stage_no
FROM (SELECT order_id, 'accepted' AS stage, 1 AS stage_no, order_moment_accepted AS m FROM orders
      UNION ALL SELECT order_id, 'ready', 2, order_moment_ready FROM orders
      UNION ALL SELECT order_id, 'collected', 3, order_moment_collected FROM orders
      UNION ALL SELECT order_id, 'in_expedition', 4, order_moment_in_expedition FROM orders
      UNION ALL SELECT order_id, 'delivering', 5, order_moment_delivering FROM orders
      UNION ALL SELECT order_id, 'delivered', 6, order_moment_delivered FROM orders
      UNION ALL SELECT order_id, 'finished', 7, order_moment_finished FROM orders)
WHERE m IS NOT NULL ORDER BY order_id, stage_no;

-- event: order_closed owner=order_id ord=close_ord
-- At `finished`, else the latest non-null moment (canceled orders have no cancel time).
SELECT (SELECT MAX(t) FROM (SELECT iso_time(order_moment_created, '%m/%d/%Y %I:%M:%S %p') AS t
        UNION ALL SELECT iso_time(order_moment_accepted, '%m/%d/%Y %I:%M:%S %p')
        UNION ALL SELECT iso_time(order_moment_ready, '%m/%d/%Y %I:%M:%S %p')
        UNION ALL SELECT iso_time(order_moment_collected, '%m/%d/%Y %I:%M:%S %p')
        UNION ALL SELECT iso_time(order_moment_in_expedition, '%m/%d/%Y %I:%M:%S %p')
        UNION ALL SELECT iso_time(order_moment_delivering, '%m/%d/%Y %I:%M:%S %p')
        UNION ALL SELECT iso_time(order_moment_delivered, '%m/%d/%Y %I:%M:%S %p')
        UNION ALL SELECT iso_time(order_moment_finished, '%m/%d/%Y %I:%M:%S %p'))) AS event_time,
       order_id, order_status, 8 AS close_ord,
       CAST(ROUND(order_delivery_cost * 100) AS INTEGER) AS order_delivery_cost,
       order_metric_collected_time, order_metric_paused_time, order_metric_production_time,
       order_metric_walking_time, order_metric_expediton_speed_time, order_metric_transit_time,
       order_metric_cycle_time
FROM orders ORDER BY order_id;

-- event: payment_recorded owner=order_id ord=payment_id
SELECT iso_time(o.order_moment_created, '%m/%d/%Y %I:%M:%S %p') AS event_time, p.payment_id,
       p.payment_order_id AS order_id,
       CAST(ROUND(p.payment_amount * 100) AS INTEGER) AS payment_amount,
       CAST(ROUND(p.payment_fee * 100) AS INTEGER) AS payment_fee, p.payment_method,
       p.payment_status
FROM payments p JOIN orders o ON o.order_id = p.payment_order_id ORDER BY p.payment_id;

-- event: delivery_assigned owner=order_id ord=delivery_id
SELECT iso_time(COALESCE(o.order_moment_delivering, o.order_moment_in_expedition,
                         o.order_moment_collected, o.order_moment_ready,
                         o.order_moment_accepted, o.order_moment_created),
                '%m/%d/%Y %I:%M:%S %p') AS event_time,
       d.delivery_id, d.delivery_order_id AS order_id, CAST(d.driver_id AS TEXT) AS driver_key,
       d.delivery_distance_meters
FROM deliveries d JOIN orders o ON o.order_id = d.delivery_order_id ORDER BY d.delivery_id;

-- event: delivery_closed owner=order_id ord=delivery_id
SELECT iso_time(COALESCE(o.order_moment_finished, o.order_moment_delivered,
                         o.order_moment_delivering, o.order_moment_in_expedition,
                         o.order_moment_collected, o.order_moment_ready,
                         o.order_moment_accepted, o.order_moment_created),
                '%m/%d/%Y %I:%M:%S %p') AS event_time,
       d.delivery_id, d.delivery_order_id AS order_id, d.delivery_status
FROM deliveries d JOIN orders o ON o.order_id = d.delivery_order_id
WHERE d.delivery_status <> 'DELIVERING' ORDER BY d.delivery_id;

-- event: stores_snapshot owner=store_key
SELECT '2021-05-08 00:00:00' AS event_time, CAST(store_id AS TEXT) AS store_key,
       store_plan_price, store_latitude, store_longitude
FROM stores ORDER BY store_id;

-- event: drivers_snapshot owner=driver_key
SELECT '2021-05-08 00:00:00' AS event_time, CAST(driver_id AS TEXT) AS driver_key,
       driver_modal, driver_type
FROM drivers ORDER BY driver_id;
