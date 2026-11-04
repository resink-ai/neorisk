-- local270: top-level packaging containers (contained in no other) with an item whose total
-- quantity, accumulated over every nested level, exceeds 500; the container and item names.
-- Written from the question (no gold SQL). Reproduces gold variant local270_b.csv, 4 of 4 rows
-- with their totals (864, 856, 720, 600); local270_a.csv is the same 4 name pairs.
WITH RECURSIVE x(top, id, qty) AS (
  SELECT p.id, r.contains_id, r.qty
  FROM packaging p JOIN packaging_relations r ON r.packaging_id = p.id
  WHERE p.id NOT IN (SELECT contains_id FROM packaging_relations)
  UNION ALL
  SELECT x.top, r.contains_id, x.qty * r.qty
  FROM x JOIN packaging_relations r ON r.packaging_id = x.id
)
SELECT t.name AS CONTAINER_NAME, i.name AS ITEM_NAME, sum(x.qty) AS TOTAL_QUANTITY
FROM x JOIN packaging t ON t.id = x.top JOIN packaging i ON i.id = x.id
GROUP BY x.top, x.id
HAVING sum(x.qty) > 500
ORDER BY TOTAL_QUANTITY DESC;
