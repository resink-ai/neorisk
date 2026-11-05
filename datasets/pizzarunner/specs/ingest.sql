-- Pizza Runner: source tables → events (refdata ingest). The clean_* and get_* tables are not
-- read: views derive them from the raw ones.

-- entity: runners event=runner_registered
SELECT CAST(runner_id AS TEXT) AS ext_id, registration_date || ' 00:00:00' AS created_at
FROM pizza_runners ORDER BY runner_id;

-- entity: pizzas
SELECT CAST(n.pizza_id AS TEXT) AS ext_id, n.pizza_name, r.toppings
FROM pizza_names n JOIN pizza_recipes r USING (pizza_id) ORDER BY n.pizza_id;

-- entity: toppings
SELECT CAST(topping_id AS TEXT) AS ext_id, topping_name FROM pizza_toppings ORDER BY topping_id;

-- entity: customers
SELECT CAST(customer_id AS TEXT) AS ext_id, MIN(order_time) AS created_at
FROM pizza_customer_orders GROUP BY customer_id ORDER BY customer_id;

-- event: pizza_ordered owner=order_id ord=src_row
SELECT order_time AS event_time, order_id, CAST(customer_id AS TEXT) AS customer_id,
       CAST(pizza_id AS TEXT) AS pizza_id, exclusions, extras, rowid AS src_row
FROM pizza_customer_orders ORDER BY rowid;

-- event: order_picked_up owner=order_id
SELECT pickup_time AS event_time, order_id, CAST(runner_id AS TEXT) AS runner_id
FROM pizza_runner_orders WHERE pickup_time IS NOT NULL ORDER BY rowid;

-- event: order_delivered owner=order_id
SELECT datetime(pickup_time, '+' || CAST(duration AS INTEGER) || ' minutes') AS event_time,
       order_id, CAST(runner_id AS TEXT) AS runner_id, distance, duration
FROM pizza_runner_orders WHERE pickup_time IS NOT NULL ORDER BY rowid;

-- event: order_cancelled owner=order_id ord=after_lines
-- At the order's time, after its lines (ord sorts it past every src_row).
SELECT (SELECT MIN(order_time) FROM pizza_customer_orders c WHERE c.order_id = r.order_id)
           AS event_time,
       order_id, CAST(runner_id AS TEXT) AS runner_id, cancellation, 1000000 AS after_lines
FROM pizza_runner_orders r WHERE cancellation IS NOT NULL ORDER BY rowid;
