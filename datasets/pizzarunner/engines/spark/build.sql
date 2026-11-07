-- Pizza Runner: events → source tables, Spark SQL port of specs/build.sql.

-- table: pizza_names
SELECT CAST(ext_id AS BIGINT) AS pizza_id, pizza_name FROM pizzas;

-- table: pizza_recipes
SELECT CAST(ext_id AS BIGINT) AS pizza_id, toppings FROM pizzas;

-- table: pizza_toppings
SELECT CAST(ext_id AS BIGINT) AS topping_id, topping_name FROM toppings;

-- table: pizza_runners
SELECT CAST(ext_id AS BIGINT) AS runner_id, date_format(created_at, 'yyyy-MM-dd') AS registration_date
FROM runners;

-- table: pizza_customer_orders
SELECT o.order_id, CAST(c.ext_id AS BIGINT) AS customer_id, CAST(p.ext_id AS BIGINT) AS pizza_id,
       o.exclusions, o.extras, date_format(o.event_time, 'yyyy-MM-dd HH:mm:ss') AS order_time
FROM pizza_ordered o JOIN customers c ON c.customer_id = o.customer_id
JOIN pizzas p ON p.pizza_id = o.pizza_id;

-- table: pizza_clean_customer_orders
-- This copy's raw rows already hold real NULLs, so cleaning changes nothing.
SELECT o.order_id, CAST(c.ext_id AS BIGINT) AS customer_id, CAST(p.ext_id AS BIGINT) AS pizza_id,
       o.exclusions, o.extras, date_format(o.event_time, 'yyyy-MM-dd HH:mm:ss') AS order_time
FROM pizza_ordered o JOIN customers c ON c.customer_id = o.customer_id
JOIN pizzas p ON p.pizza_id = o.pizza_id;

-- table: pizza_runner_orders
SELECT u.order_id, CAST(r.ext_id AS BIGINT) AS runner_id,
       date_format(u.event_time, 'yyyy-MM-dd HH:mm:ss') AS pickup_time,
       d.distance, d.duration, CAST(NULL AS STRING) AS cancellation
FROM order_picked_up u JOIN order_delivered d ON d.order_id = u.order_id
JOIN runners r ON r.runner_id = u.runner_id
UNION ALL
SELECT x.order_id, CAST(r.ext_id AS BIGINT), CAST(NULL AS STRING), CAST(NULL AS STRING),
       CAST(NULL AS STRING), CAST(x.cancellation AS STRING)
FROM order_cancelled x JOIN runners r ON r.runner_id = x.runner_id;

-- table: pizza_clean_runner_orders
-- SQLite's CAST reads the leading number ('20km' → 20.0); the cleaner wrote 0.0 for missing.
WITH r AS (
  SELECT u.order_id, u.runner_id, u.event_time AS pickup, d.distance, d.duration,
         CAST(NULL AS STRING) AS cancellation
  FROM order_picked_up u JOIN order_delivered d ON d.order_id = u.order_id
  UNION ALL
  SELECT order_id, runner_id, CAST(NULL AS TIMESTAMP), CAST(NULL AS STRING),
         CAST(NULL AS STRING), CAST(cancellation AS STRING) FROM order_cancelled)
SELECT r.order_id, CAST(n.ext_id AS BIGINT) AS runner_id,
       date_format(r.pickup, 'yyyy-MM-dd HH:mm:ss') AS pickup_time,
       coalesce(try_cast(nullif(regexp_extract(r.distance, '^[0-9]+(\\.[0-9]+)?', 0), '')
                         AS DOUBLE), 0.0) AS distance,
       coalesce(try_cast(nullif(regexp_extract(r.duration, '^[0-9]+(\\.[0-9]+)?', 0), '')
                         AS DOUBLE), 0.0) AS duration,
       r.cancellation
FROM r JOIN runners n ON n.runner_id = r.runner_id;

-- table: pizza_get_extras
-- One row per distinct (order, topping): row_id ranks first appearance, the count is every
-- token in the order.
WITH tok AS (
  SELECT order_id, src_row, CAST(trim(x.col) AS BIGINT) AS t, x.pos + 1 AS pos
  FROM pizza_ordered LATERAL VIEW posexplode(split(extras, ',')) x AS pos, col
  WHERE extras IS NOT NULL),
firsts AS (SELECT order_id, t, min(src_row * 1000 + pos) AS seen, max(n) AS n
           FROM (SELECT *, count(*) OVER (PARTITION BY order_id) AS n FROM tok)
           GROUP BY order_id, t)
SELECT row_number() OVER (PARTITION BY order_id ORDER BY seen) AS row_id, order_id,
       t AS extras, n AS extras_count
FROM firsts;

-- table: pizza_get_exclusions
WITH tok AS (
  SELECT order_id, src_row, CAST(trim(x.col) AS BIGINT) AS t, x.pos + 1 AS pos
  FROM pizza_ordered LATERAL VIEW posexplode(split(exclusions, ',')) x AS pos, col
  WHERE exclusions IS NOT NULL),
firsts AS (SELECT order_id, t, min(src_row * 1000 + pos) AS seen, max(n) AS n
           FROM (SELECT *, count(*) OVER (PARTITION BY order_id) AS n FROM tok)
           GROUP BY order_id, t)
SELECT row_number() OVER (PARTITION BY order_id ORDER BY seen) AS row_id, order_id,
       t AS exclusions, n AS total_exclusions
FROM firsts;
