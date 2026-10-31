-- Pizza Runner: events → source tables (refdata rebuild, DuckDB).

-- table: pizza_names
SELECT CAST(ext_id AS BIGINT) AS pizza_id, pizza_name FROM pizzas;

-- table: pizza_recipes
SELECT CAST(ext_id AS BIGINT) AS pizza_id, toppings FROM pizzas;

-- table: pizza_toppings
SELECT CAST(ext_id AS BIGINT) AS topping_id, topping_name FROM toppings;

-- table: pizza_runners
SELECT CAST(ext_id AS BIGINT) AS runner_id,
       strftime(created_at AT TIME ZONE 'UTC', '%Y-%m-%d') AS registration_date
FROM runners;

-- table: pizza_customer_orders
SELECT o.order_id, CAST(c.ext_id AS BIGINT) AS customer_id, CAST(p.ext_id AS BIGINT) AS pizza_id,
       o.exclusions, o.extras,
       strftime(o.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS order_time
FROM pizza_ordered o JOIN customers c USING (customer_id) JOIN pizzas p USING (pizza_id)
ORDER BY o.src_row;

-- table: pizza_clean_customer_orders
-- This copy's raw rows already hold real NULLs, so cleaning changes nothing.
SELECT o.order_id, CAST(c.ext_id AS BIGINT) AS customer_id, CAST(p.ext_id AS BIGINT) AS pizza_id,
       o.exclusions, o.extras,
       strftime(o.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS order_time
FROM pizza_ordered o JOIN customers c USING (customer_id) JOIN pizzas p USING (pizza_id)
ORDER BY o.src_row;

-- table: pizza_runner_orders
SELECT u.order_id, CAST(r.ext_id AS BIGINT) AS runner_id,
       strftime(u.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS pickup_time,
       d.distance, d.duration, NULL::VARCHAR AS cancellation
FROM order_picked_up u JOIN order_delivered d USING (order_id) JOIN runners r
    ON r.runner_id = u.runner_id
UNION ALL
SELECT x.order_id, CAST(r.ext_id AS BIGINT), NULL, NULL, NULL, CAST(x.cancellation AS VARCHAR)
FROM order_cancelled x JOIN runners r USING (runner_id)
ORDER BY order_id;

-- table: pizza_clean_runner_orders
-- SQLite's CAST reads the leading number ('20km' → 20.0); the cleaner wrote 0.0 for missing.
WITH r AS (
  SELECT u.order_id, u.runner_id, u.event_time AS pickup, d.distance, d.duration,
         NULL::VARCHAR AS cancellation
  FROM order_picked_up u JOIN order_delivered d USING (order_id)
  UNION ALL
  SELECT order_id, runner_id, NULL, NULL, NULL, CAST(cancellation AS VARCHAR) FROM order_cancelled)
SELECT r.order_id, CAST(n.ext_id AS BIGINT) AS runner_id,
       strftime(r.pickup AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS pickup_time,
       coalesce(TRY_CAST(regexp_extract(r.distance, '^[0-9]+(\.[0-9]+)?') AS DOUBLE), 0.0)
           AS distance,
       coalesce(TRY_CAST(regexp_extract(r.duration, '^[0-9]+(\.[0-9]+)?') AS DOUBLE), 0.0)
           AS duration,
       r.cancellation
FROM r JOIN runners n USING (runner_id)
ORDER BY r.order_id;

-- table: pizza_get_extras
-- One row per distinct (order, topping): row_id ranks first appearance, the count is every
-- token in the order.
WITH tok AS (
  SELECT order_id, src_row, CAST(trim(unnest(string_split(extras, ','))) AS BIGINT) AS t,
         unnest(range(1, len(string_split(extras, ',')) + 1)) AS pos
  FROM pizza_ordered WHERE extras IS NOT NULL),
firsts AS (SELECT order_id, t, min(src_row * 1000 + pos) AS seen, any_value(n) AS n
          FROM (SELECT *, count(*) OVER (PARTITION BY order_id) AS n FROM tok)
          GROUP BY order_id, t)
SELECT row_number() OVER (PARTITION BY order_id ORDER BY seen) AS row_id, order_id,
       t AS extras, n AS extras_count
FROM firsts ORDER BY order_id, row_id;

-- table: pizza_get_exclusions
WITH tok AS (
  SELECT order_id, src_row, CAST(trim(unnest(string_split(exclusions, ','))) AS BIGINT) AS t,
         unnest(range(1, len(string_split(exclusions, ',')) + 1)) AS pos
  FROM pizza_ordered WHERE exclusions IS NOT NULL),
firsts AS (SELECT order_id, t, min(src_row * 1000 + pos) AS seen, any_value(n) AS n
          FROM (SELECT *, count(*) OVER (PARTITION BY order_id) AS n FROM tok)
          GROUP BY order_id, t)
SELECT row_number() OVER (PARTITION BY order_id ORDER BY seen) AS row_id, order_id,
       t AS exclusions, n AS total_exclusions
FROM firsts ORDER BY order_id, row_id;
