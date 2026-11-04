-- local263: per status, the L1_model most often associated with a run (name, version), and
-- its count. A run is 'strong' if any of its steps is strong in the source view stack_ok,
-- otherwise 'soft' if any step is soft (one status per run).
-- Written from the question (no gold SQL), over the replayed view stack_ok. Reproduces gold
-- variant local263_a.csv: soft regression 17, strong regression 37. (Counting stack_ok rows
-- instead gives 36 and 78.)
WITH nv AS (SELECT name, version, L1_model, max(status = 'strong') AS any_strong
            FROM stack_ok GROUP BY name, version, L1_model),
c AS (SELECT CASE WHEN any_strong THEN 'strong' ELSE 'soft' END AS status, L1_model,
             count(*) AS n
      FROM nv GROUP BY 1, 2),
r AS (SELECT status, L1_model, n, rank() OVER (PARTITION BY status ORDER BY n DESC) AS rk
      FROM c)
SELECT status AS STATUS, L1_model AS L1_MODEL, n AS OCCURRENCES
FROM r WHERE rk = 1
ORDER BY status;
