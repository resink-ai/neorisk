-- local073: per pizza line, the final ingredients: recipe − exclusions + extras, as
-- '<name>: ' then the '2x' toppings and then the single ones, each alphabetical.
-- Written from the question (no gold SQL); matches every row of the accepted CSVs _a and _b.
WITH RECURSIVE
lines AS (SELECT rowid AS row_id, order_id, customer_id, pizza_id, exclusions, extras
          FROM pizza_clean_customer_orders),
split(row_id, kind, rest, tok) AS (
  SELECT l.row_id, 'r', r.toppings || ',', NULL FROM lines l JOIN pizza_recipes r USING (pizza_id)
  UNION ALL SELECT row_id, 'x', exclusions || ',', NULL FROM lines WHERE exclusions IS NOT NULL
  UNION ALL SELECT row_id, 'e', extras || ',', NULL FROM lines WHERE extras IS NOT NULL
  UNION ALL
  SELECT row_id, kind, substr(rest, instr(rest, ',') + 1),
         CAST(trim(substr(rest, 1, instr(rest, ',') - 1)) AS INTEGER)
  FROM split WHERE rest <> ''),
toks AS (SELECT row_id, kind, tok FROM split WHERE tok IS NOT NULL),
kept AS (
  SELECT row_id, tok FROM toks t WHERE kind = 'r' AND NOT EXISTS (
    SELECT 1 FROM toks x WHERE x.row_id = t.row_id AND x.kind = 'x' AND x.tok = t.tok)
  UNION ALL SELECT row_id, tok FROM toks WHERE kind = 'e'),
counted AS (
  SELECT k.row_id, p.topping_name AS name, count(*) AS n
  FROM kept k JOIN pizza_toppings p ON p.topping_id = k.tok GROUP BY k.row_id, p.topping_name),
labels AS (
  SELECT row_id, group_concat(label, ', ') AS ing FROM (
    SELECT row_id, CASE WHEN n > 1 THEN '2x ' || name ELSE name END AS label
    FROM counted ORDER BY row_id, n > 1 DESC, name)
  GROUP BY row_id)
SELECT l.row_id, l.order_id, l.customer_id, n.pizza_name,
       n.pizza_name || ': ' || b.ing AS ingredients
FROM lines l JOIN pizza_names n USING (pizza_id) JOIN labels b USING (row_id)
ORDER BY l.row_id;
