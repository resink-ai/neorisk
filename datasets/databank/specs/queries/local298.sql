-- local298: for each month, the sum over customers of max(0, balance as of the 1st), first
-- month excluded. Reproduces the gold result (research: scripts/a_databank.py).
WITH d AS (SELECT customer_id, txn_date,
                  CASE WHEN txn_type = 'deposit' THEN txn_amount ELSE -txn_amount END AS v
           FROM customer_transactions),
     m AS (SELECT DISTINCT substr(txn_date, 1, 7) || '-01' AS m FROM customer_transactions),
     c AS (SELECT DISTINCT customer_id FROM customer_transactions),
     t AS (SELECT m.m, SUM(MAX(0, COALESCE((SELECT SUM(v) FROM d
                                           WHERE d.customer_id = c.customer_id
                                             AND d.txn_date < m.m), 0))) AS total
           FROM m, c GROUP BY 1)
SELECT m AS month, total FROM t WHERE m > (SELECT MIN(m) FROM m) ORDER BY m;
