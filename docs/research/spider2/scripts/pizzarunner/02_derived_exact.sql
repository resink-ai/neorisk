-- Are pizza_clean_* and pizza_get_* exact functions of the raw tables?
-- Run: sqlite3 -readonly data/spider2/modern_data.sqlite < docs/research/spider2/scripts/pizzarunner/02_derived_exact.sql
.headers on
.mode list

-- 1. clean_customer_orders vs customer_orders: row-by-row (rowid) and type-by-type
SELECT 'clean_co_rowwise_diff' k, count(*) n FROM pizza_customer_orders a JOIN pizza_clean_customer_orders b ON a.rowid=b.rowid
WHERE a.order_id IS NOT b.order_id OR a.customer_id IS NOT b.customer_id OR a.pizza_id IS NOT b.pizza_id
   OR a.exclusions IS NOT b.exclusions OR a.extras IS NOT b.extras OR a.order_time IS NOT b.order_time
   OR typeof(a.exclusions)<>typeof(b.exclusions) OR typeof(a.extras)<>typeof(b.extras);
SELECT 'clean_co_multiset_diff' k, (SELECT count(*) FROM (SELECT * FROM pizza_customer_orders EXCEPT SELECT * FROM pizza_clean_customer_orders))
  + (SELECT count(*) FROM (SELECT * FROM pizza_clean_customer_orders EXCEPT SELECT * FROM pizza_customer_orders)) n;

-- 2. clean_runner_orders = f(runner_orders) with
--    distance = coalesce(CAST(distance AS REAL), 0.0); duration = coalesce(CAST(duration AS REAL), 0.0)
--    (SQLite CAST reads the longest numeric prefix: '13.4km' -> 13.4, '32 minutes' -> 32.0, '23.4 km' -> 23.4)
WITH f AS (
  SELECT rowid r, order_id, runner_id, pickup_time,
         coalesce(CAST(distance AS REAL), 0.0) distance,
         coalesce(CAST(duration AS REAL), 0.0) duration,
         cancellation
  FROM pizza_runner_orders)
SELECT 'clean_ro_rule_rowwise_diff' k, count(*) n FROM f JOIN pizza_clean_runner_orders b ON f.r=b.rowid
WHERE f.order_id IS NOT b.order_id OR f.runner_id IS NOT b.runner_id OR f.pickup_time IS NOT b.pickup_time
   OR f.distance IS NOT b.distance OR f.duration IS NOT b.duration OR f.cancellation IS NOT b.cancellation
   OR typeof(f.distance)<>typeof(b.distance) OR typeof(f.duration)<>typeof(b.duration);
-- the alternative "keep NULL" rule (CAST without coalesce) differs on the cancelled rows
SELECT 'clean_ro_keepnull_rule_diff' k, count(*) n FROM pizza_runner_orders a JOIN pizza_clean_runner_orders b ON a.rowid=b.rowid
WHERE CAST(a.distance AS REAL) IS NOT b.distance OR CAST(a.duration AS REAL) IS NOT b.duration;

-- 3. get_extras / get_exclusions: split every comma list of customer_orders into tokens, keep the
--    position; one output row per DISTINCT (order_id, token), row_id = rank of the token's first
--    appearance in the order, count column = number of token occurrences in the whole order.
WITH RECURSIVE sp(src, r, order_id, pos, tok, rest) AS (
  SELECT 'x', rowid, order_id, 0, NULL, exclusions || ',' FROM pizza_customer_orders WHERE exclusions IS NOT NULL
  UNION ALL
  SELECT 'e', rowid, order_id, 0, NULL, extras || ',' FROM pizza_customer_orders WHERE extras IS NOT NULL
  UNION ALL
  SELECT src, r, order_id, pos+1, CAST(trim(substr(rest,1,instr(rest,',')-1)) AS INTEGER), substr(rest, instr(rest,',')+1)
  FROM sp WHERE rest <> ''),
tok AS (SELECT * FROM sp WHERE tok IS NOT NULL),
firsts AS (SELECT src, order_id, tok, min(r*100+pos) first_at FROM tok GROUP BY src, order_id, tok),
tot AS (SELECT src, order_id, count(*) n FROM tok GROUP BY src, order_id),
der AS (SELECT f.src, row_number() OVER (PARTITION BY f.src, f.order_id ORDER BY f.first_at) row_id, f.order_id, f.tok, t.n
        FROM firsts f JOIN tot t USING (src, order_id))
SELECT 'get_extras_diff' k,
  (SELECT count(*) FROM (SELECT row_id, order_id, tok, n FROM der WHERE src='e' EXCEPT SELECT * FROM pizza_get_extras))
 +(SELECT count(*) FROM (SELECT * FROM pizza_get_extras EXCEPT SELECT row_id, order_id, tok, n FROM der WHERE src='e')) n,
  (SELECT count(*) FROM der WHERE src='e') derived_rows
UNION ALL
SELECT 'get_exclusions_diff',
  (SELECT count(*) FROM (SELECT row_id, order_id, tok, n FROM der WHERE src='x' EXCEPT SELECT * FROM pizza_get_exclusions))
 +(SELECT count(*) FROM (SELECT * FROM pizza_get_exclusions EXCEPT SELECT row_id, order_id, tok, n FROM der WHERE src='x')),
  (SELECT count(*) FROM der WHERE src='x');

-- token-level facts that make the rule ambiguous or not
WITH RECURSIVE sp(src, r, order_id, tok, rest) AS (
  SELECT 'x', rowid, order_id, NULL, exclusions || ',' FROM pizza_customer_orders WHERE exclusions IS NOT NULL
  UNION ALL SELECT 'e', rowid, order_id, NULL, extras || ',' FROM pizza_customer_orders WHERE extras IS NOT NULL
  UNION ALL SELECT src, r, order_id, trim(substr(rest,1,instr(rest,',')-1)), substr(rest, instr(rest,',')+1) FROM sp WHERE rest <> '')
SELECT 'tokens' k, src, count(*) tokens, count(DISTINCT order_id||'-'||tok) distinct_order_tok,
       sum(tok GLOB '*[^0-9]*') non_digit_tokens,
       (SELECT count(*) FROM pizza_customer_orders WHERE coalesce(exclusions,'')||coalesce(extras,'') LIKE '% %') lists_with_space
FROM sp WHERE tok IS NOT NULL GROUP BY src;
SELECT 'tokens_ascending_in_list' k, count(*) FROM pizza_customer_orders WHERE exclusions LIKE '%,%' OR extras LIKE '%,%';
SELECT 'recipe_list_format' k, pizza_id, toppings, length(toppings) - length(replace(toppings, ', ', ',')) sep_with_space,
       (length(toppings) - length(replace(toppings, ',', ''))) + 1 n_tokens FROM pizza_recipes;
-- every token is a known topping
WITH RECURSIVE sp(tok, rest) AS (
  SELECT NULL, coalesce(exclusions,'') || ',' || coalesce(extras,'') || ',' FROM pizza_customer_orders
  UNION ALL SELECT NULL, toppings || ',' FROM pizza_recipes
  UNION ALL SELECT trim(substr(rest,1,instr(rest,',')-1)), substr(rest, instr(rest,',')+1) FROM sp WHERE rest <> '')
SELECT 'orphan_topping_tokens' k, count(*) FROM sp WHERE tok IS NOT NULL AND tok <> '' AND CAST(tok AS INTEGER) NOT IN (SELECT topping_id FROM pizza_toppings);
-- extras that are already in the recipe (=> "2x" in local073) and exclusions not in the recipe
WITH RECURSIVE sp(r, pizza_id, src, tok, rest) AS (
  SELECT rowid, pizza_id, 'e', NULL, extras||',' FROM pizza_customer_orders WHERE extras IS NOT NULL
  UNION ALL SELECT rowid, pizza_id, 'x', NULL, exclusions||',' FROM pizza_customer_orders WHERE exclusions IS NOT NULL
  UNION ALL SELECT r, pizza_id, src, trim(substr(rest,1,instr(rest,',')-1)), substr(rest, instr(rest,',')+1) FROM sp WHERE rest <> '')
SELECT 'token_in_recipe' k, src, sum(instr(', '||rc.toppings||',', ', '||tok||',')>0) in_recipe, count(*) total
FROM sp JOIN pizza_recipes rc USING (pizza_id) WHERE tok IS NOT NULL GROUP BY src;
-- physical order of get_* tables
SELECT 'get_extras_rows' k, group_concat(order_id||':'||row_id||':'||extras, ' ') FROM pizza_get_extras;
SELECT 'get_exclusions_rows' k, group_concat(order_id||':'||row_id||':'||exclusions, ' ') FROM pizza_get_exclusions;
