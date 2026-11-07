-- Pizza Runner: events → source tables, Flink SQL port of specs/build.sql, for `flink` and
-- `flink-stream`. No OVER windows: ranks and per-order counts are self-joins and GROUP BYs,
-- which the streaming planner also accepts.

-- table: pizza_names
SELECT CAST(ext_id AS BIGINT) AS pizza_id, pizza_name FROM pizzas;

-- table: pizza_recipes
SELECT CAST(ext_id AS BIGINT) AS pizza_id, toppings FROM pizzas;

-- table: pizza_toppings
SELECT CAST(ext_id AS BIGINT) AS topping_id, topping_name FROM toppings;

-- table: pizza_runners
SELECT CAST(ext_id AS BIGINT) AS runner_id, DATE_FORMAT(created_at, 'yyyy-MM-dd') AS registration_date
FROM runners;

-- table: pizza_customer_orders
SELECT o.order_id, CAST(c.ext_id AS BIGINT) AS customer_id, CAST(p.ext_id AS BIGINT) AS pizza_id,
       o.exclusions, o.extras, DATE_FORMAT(o.event_time, 'yyyy-MM-dd HH:mm:ss') AS order_time
FROM pizza_ordered o JOIN customers c ON c.customer_id = o.customer_id
JOIN pizzas p ON p.pizza_id = o.pizza_id;

-- table: pizza_clean_customer_orders
-- This copy's raw rows already hold real NULLs, so cleaning changes nothing.
SELECT o.order_id, CAST(c.ext_id AS BIGINT) AS customer_id, CAST(p.ext_id AS BIGINT) AS pizza_id,
       o.exclusions, o.extras, DATE_FORMAT(o.event_time, 'yyyy-MM-dd HH:mm:ss') AS order_time
FROM pizza_ordered o JOIN customers c ON c.customer_id = o.customer_id
JOIN pizzas p ON p.pizza_id = o.pizza_id;

-- table: pizza_runner_orders
SELECT u.order_id, CAST(r.ext_id AS BIGINT) AS runner_id,
       DATE_FORMAT(u.event_time, 'yyyy-MM-dd HH:mm:ss') AS pickup_time,
       d.distance, d.duration, CAST(NULL AS STRING) AS cancellation
FROM order_picked_up u JOIN order_delivered d ON d.order_id = u.order_id
JOIN runners r ON r.runner_id = u.runner_id
UNION ALL
SELECT x.order_id, CAST(r.ext_id AS BIGINT), CAST(NULL AS STRING), CAST(NULL AS STRING),
       CAST(NULL AS STRING), CAST(x.cancellation AS STRING)
FROM order_cancelled x JOIN runners r ON r.runner_id = x.runner_id;

-- table: pizza_clean_runner_orders
-- SQLite's CAST reads the leading number ('20km' → 20.0); the cleaner wrote 0.0 for missing.
SELECT r.order_id, CAST(n.ext_id AS BIGINT) AS runner_id,
       DATE_FORMAT(r.pickup, 'yyyy-MM-dd HH:mm:ss') AS pickup_time,
       COALESCE(TRY_CAST(REGEXP_EXTRACT(r.distance, '^[0-9]+(\.[0-9]+)?', 0) AS DOUBLE), 0.0)
           AS distance,
       COALESCE(TRY_CAST(REGEXP_EXTRACT(r.duration, '^[0-9]+(\.[0-9]+)?', 0) AS DOUBLE), 0.0)
           AS duration,
       r.cancellation
FROM (SELECT u.order_id, u.runner_id, u.event_time AS pickup, d.distance, d.duration,
             CAST(NULL AS STRING) AS cancellation
      FROM order_picked_up u JOIN order_delivered d ON d.order_id = u.order_id
      UNION ALL
      SELECT order_id, runner_id, CAST(NULL AS TIMESTAMP(6)), CAST(NULL AS STRING),
             CAST(NULL AS STRING), CAST(cancellation AS STRING) FROM order_cancelled) r
JOIN runners n ON n.runner_id = r.runner_id;

-- table: pizza_get_extras
-- One row per distinct (order, topping): row_id ranks first appearance (the number of
-- distinct toppings seen no later), the count is every token in the order.
SELECT a.row_id, a.order_id, a.t AS extras, c.n AS extras_count
FROM (SELECT f.order_id, f.t, COUNT(*) AS row_id
      FROM (SELECT order_id, t, MIN(seen) AS seen FROM (
              SELECT o.order_id, CAST(TRIM(x.tok) AS BIGINT) AS t, o.src_row * 1000 + x.pos AS seen
              FROM pizza_ordered o CROSS JOIN UNNEST(SPLIT(o.extras, ',')) WITH ORDINALITY AS x(tok, pos)
              WHERE o.extras IS NOT NULL) GROUP BY order_id, t) f
      JOIN (SELECT order_id, t, MIN(seen) AS seen FROM (
              SELECT o.order_id, CAST(TRIM(x.tok) AS BIGINT) AS t, o.src_row * 1000 + x.pos AS seen
              FROM pizza_ordered o CROSS JOIN UNNEST(SPLIT(o.extras, ',')) WITH ORDINALITY AS x(tok, pos)
              WHERE o.extras IS NOT NULL) GROUP BY order_id, t) g
        ON g.order_id = f.order_id AND g.seen <= f.seen
      GROUP BY f.order_id, f.t) a
JOIN (SELECT o.order_id, COUNT(*) AS n
      FROM pizza_ordered o CROSS JOIN UNNEST(SPLIT(o.extras, ',')) WITH ORDINALITY AS x(tok, pos)
      WHERE o.extras IS NOT NULL GROUP BY o.order_id) c ON c.order_id = a.order_id;

-- table: pizza_get_exclusions
SELECT a.row_id, a.order_id, a.t AS exclusions, c.n AS total_exclusions
FROM (SELECT f.order_id, f.t, COUNT(*) AS row_id
      FROM (SELECT order_id, t, MIN(seen) AS seen FROM (
              SELECT o.order_id, CAST(TRIM(x.tok) AS BIGINT) AS t, o.src_row * 1000 + x.pos AS seen
              FROM pizza_ordered o CROSS JOIN UNNEST(SPLIT(o.exclusions, ',')) WITH ORDINALITY AS x(tok, pos)
              WHERE o.exclusions IS NOT NULL) GROUP BY order_id, t) f
      JOIN (SELECT order_id, t, MIN(seen) AS seen FROM (
              SELECT o.order_id, CAST(TRIM(x.tok) AS BIGINT) AS t, o.src_row * 1000 + x.pos AS seen
              FROM pizza_ordered o CROSS JOIN UNNEST(SPLIT(o.exclusions, ',')) WITH ORDINALITY AS x(tok, pos)
              WHERE o.exclusions IS NOT NULL) GROUP BY order_id, t) g
        ON g.order_id = f.order_id AND g.seen <= f.seen
      GROUP BY f.order_id, f.t) a
JOIN (SELECT o.order_id, COUNT(*) AS n
      FROM pizza_ordered o CROSS JOIN UNNEST(SPLIT(o.exclusions, ',')) WITH ORDINALITY AS x(tok, pos)
      WHERE o.exclusions IS NOT NULL GROUP BY o.order_id) c ON c.order_id = a.order_id;
