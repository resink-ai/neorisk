-- local269: the average total leaf quantity per top-level packaging, after expanding the
-- nested packaging relations and multiplying quantities down the tree.
-- Written from the question (no gold SQL). Reproduces gold variant local269_a.csv: 946.0,
-- the average of 864, 720, 960 and 1240 over the 4 pallets.
WITH RECURSIVE x(top, id, qty) AS (
  SELECT p.id, r.contains_id, r.qty
  FROM packaging p JOIN packaging_relations r ON r.packaging_id = p.id
  WHERE p.id NOT IN (SELECT contains_id FROM packaging_relations)
  UNION ALL
  SELECT x.top, r.contains_id, x.qty * r.qty
  FROM x JOIN packaging_relations r ON r.packaging_id = x.id
)
SELECT avg(total) AS AVERAGE_TOTAL_QUANTITY
FROM (SELECT top, sum(qty) AS total FROM x
      WHERE id NOT IN (SELECT packaging_id FROM packaging_relations) GROUP BY top);
