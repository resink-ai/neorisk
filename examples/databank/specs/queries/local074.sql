-- local074: month-end closing balance per customer, monthly change and cumulative balance,
-- including months without activity. Written from the question (no gold SQL in Spider2).
WITH months AS (SELECT DISTINCT substr(txn_date, 1, 7) AS m FROM customer_transactions),
     cust AS (SELECT DISTINCT customer_id FROM customer_transactions),
     net AS (SELECT customer_id, substr(txn_date, 1, 7) AS m,
                    SUM(CASE WHEN txn_type = 'deposit' THEN txn_amount ELSE -txn_amount END) AS chg
             FROM customer_transactions GROUP BY 1, 2)
SELECT c.customer_id, mo.m AS month, COALESCE(n.chg, 0) AS monthly_change,
       SUM(COALESCE(n.chg, 0)) OVER (PARTITION BY c.customer_id ORDER BY mo.m) AS closing_balance
FROM cust c CROSS JOIN months mo
LEFT JOIN net n ON n.customer_id = c.customer_id AND n.m = mo.m
ORDER BY c.customer_id, mo.m;
