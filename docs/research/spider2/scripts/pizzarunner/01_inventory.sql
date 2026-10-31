-- Run: sqlite3 -readonly data/spider2/modern_data.sqlite < docs/research/spider2/scripts/pizzarunner/01_inventory.sql
.headers on
.mode list
SELECT 'customer_orders' t, count(*) n FROM pizza_customer_orders UNION ALL
SELECT 'clean_customer_orders', count(*) FROM pizza_clean_customer_orders UNION ALL
SELECT 'runner_orders', count(*) FROM pizza_runner_orders UNION ALL
SELECT 'clean_runner_orders', count(*) FROM pizza_clean_runner_orders UNION ALL
SELECT 'runners', count(*) FROM pizza_runners UNION ALL
SELECT 'names', count(*) FROM pizza_names UNION ALL
SELECT 'recipes', count(*) FROM pizza_recipes UNION ALL
SELECT 'toppings', count(*) FROM pizza_toppings UNION ALL
SELECT 'get_extras', count(*) FROM pizza_get_extras UNION ALL
SELECT 'get_exclusions', count(*) FROM pizza_get_exclusions;

-- storage types per column (raw tables)
SELECT 'co.' || c, typeof(v) ty, count(*) n FROM (
  SELECT 'order_id' c, order_id v FROM pizza_customer_orders UNION ALL
  SELECT 'customer_id', customer_id FROM pizza_customer_orders UNION ALL
  SELECT 'pizza_id', pizza_id FROM pizza_customer_orders UNION ALL
  SELECT 'exclusions', exclusions FROM pizza_customer_orders UNION ALL
  SELECT 'extras', extras FROM pizza_customer_orders UNION ALL
  SELECT 'order_time', order_time FROM pizza_customer_orders) GROUP BY 1,2;
SELECT 'ro.' || c, typeof(v) ty, count(*) n FROM (
  SELECT 'pickup_time' c, pickup_time v FROM pizza_runner_orders UNION ALL
  SELECT 'distance', distance FROM pizza_runner_orders UNION ALL
  SELECT 'duration', duration FROM pizza_runner_orders UNION ALL
  SELECT 'cancellation', cancellation FROM pizza_runner_orders) GROUP BY 1,2;
SELECT 'cro.' || c, typeof(v) ty, count(*) n FROM (
  SELECT 'pickup_time' c, pickup_time v FROM pizza_clean_runner_orders UNION ALL
  SELECT 'distance', distance FROM pizza_clean_runner_orders UNION ALL
  SELECT 'duration', duration FROM pizza_clean_runner_orders UNION ALL
  SELECT 'cancellation', cancellation FROM pizza_clean_runner_orders) GROUP BY 1,2;
SELECT 'ge.' || c, typeof(v) ty, count(*) n FROM (
  SELECT 'row_id' c, row_id v FROM pizza_get_extras UNION ALL
  SELECT 'extras', extras FROM pizza_get_extras UNION ALL
  SELECT 'extras_count', extras_count FROM pizza_get_extras UNION ALL
  SELECT 'x.row_id', row_id FROM pizza_get_exclusions UNION ALL
  SELECT 'x.exclusions', exclusions FROM pizza_get_exclusions UNION ALL
  SELECT 'x.total_exclusions', total_exclusions FROM pizza_get_exclusions) GROUP BY 1,2;
SELECT 'other.' || c, typeof(v) ty, count(*) n FROM (
  SELECT 'runners.registration_date' c, registration_date v FROM pizza_runners UNION ALL
  SELECT 'recipes.toppings', toppings FROM pizza_recipes UNION ALL
  SELECT 'names.pizza_name', pizza_name FROM pizza_names UNION ALL
  SELECT 'toppings.topping_name', topping_name FROM pizza_toppings) GROUP BY 1,2;

-- 'null' strings, '' and '\N' anywhere in the text columns of the pizza tables
SELECT 'dirty_tokens' k, count(*) n FROM (
  SELECT exclusions v FROM pizza_customer_orders UNION ALL SELECT extras FROM pizza_customer_orders UNION ALL
  SELECT order_time FROM pizza_customer_orders UNION ALL SELECT pickup_time FROM pizza_runner_orders UNION ALL
  SELECT distance FROM pizza_runner_orders UNION ALL SELECT duration FROM pizza_runner_orders UNION ALL
  SELECT cancellation FROM pizza_runner_orders UNION ALL SELECT exclusions FROM pizza_clean_customer_orders UNION ALL
  SELECT extras FROM pizza_clean_customer_orders UNION ALL SELECT cancellation FROM pizza_clean_runner_orders UNION ALL
  SELECT pickup_time FROM pizza_clean_runner_orders)
WHERE lower(trim(v)) IN ('null','', '\n') OR v = '\N';

-- keys
SELECT 'co_full_dup_groups' k, count(*) FROM (SELECT 1 FROM pizza_customer_orders GROUP BY order_id,customer_id,pizza_id,exclusions,extras,order_time HAVING count(*)>1);
SELECT 'co_orders' k, count(DISTINCT order_id), count(DISTINCT customer_id) FROM pizza_customer_orders;
SELECT 'co_order_one_customer_one_time' k, count(*) FROM (SELECT order_id FROM pizza_customer_orders GROUP BY order_id HAVING count(DISTINCT customer_id)>1 OR count(DISTINCT order_time)>1);
SELECT 'ro_order_id_unique' k, count(*), count(DISTINCT order_id) FROM pizza_runner_orders;
SELECT 'runner_id_unique' k, count(*), count(DISTINCT runner_id) FROM pizza_runners;
SELECT 'topping_id_unique' k, count(*), count(DISTINCT topping_id) FROM pizza_toppings;
SELECT 'pizza_id_unique' k, (SELECT count(DISTINCT pizza_id) FROM pizza_names), (SELECT count(DISTINCT pizza_id) FROM pizza_recipes);
-- orphans
SELECT 'orphan_co_pizza' k, count(*) FROM pizza_customer_orders WHERE pizza_id NOT IN (SELECT pizza_id FROM pizza_names);
SELECT 'orphan_ro_order' k, count(*) FROM pizza_runner_orders WHERE order_id NOT IN (SELECT order_id FROM pizza_customer_orders);
SELECT 'orders_without_ro' k, count(*) FROM (SELECT DISTINCT order_id FROM pizza_customer_orders) WHERE order_id NOT IN (SELECT order_id FROM pizza_runner_orders);
SELECT 'orphan_ro_runner' k, count(*) FROM pizza_runner_orders WHERE runner_id NOT IN (SELECT runner_id FROM pizza_runners);
SELECT 'runners_without_orders' k, group_concat(runner_id) FROM pizza_runners WHERE runner_id NOT IN (SELECT runner_id FROM pizza_runner_orders);
SELECT 'orders_per_runner' k, runner_id, count(*), sum(cancellation IS NULL) FROM pizza_runner_orders GROUP BY runner_id;
SELECT 'orders_per_customer' k, customer_id, count(DISTINCT order_id), count(*) FROM pizza_customer_orders GROUP BY customer_id;
SELECT 'pizzas_per_order' k, n, count(*) FROM (SELECT order_id, count(*) n FROM pizza_customer_orders GROUP BY order_id) GROUP BY n;
SELECT 'physical_order_sorted' k,
  (SELECT count(*) FROM pizza_customer_orders a JOIN pizza_customer_orders b ON b.rowid=a.rowid+1 WHERE b.order_time < a.order_time OR b.order_id < a.order_id) co_desc,
  (SELECT count(*) FROM pizza_runner_orders a JOIN pizza_runner_orders b ON b.rowid=a.rowid+1 WHERE b.order_id < a.order_id) ro_desc;
SELECT 'order_id_vs_time_rank_mismatch' k, count(*) FROM (SELECT order_id, min(order_time) t FROM pizza_customer_orders GROUP BY order_id) a
  WHERE (SELECT count(*) FROM (SELECT order_id, min(order_time) t FROM pizza_customer_orders GROUP BY order_id) b WHERE b.t < a.t) <> a.order_id - 1;
