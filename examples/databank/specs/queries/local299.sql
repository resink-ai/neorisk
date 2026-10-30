-- local299: daily running balance (deposits +, others -); 30-day rolling average once 30 days
-- of history exist, negatives as 0; per customer the monthly max; summed per month, each
-- customer's first month excluded. Written from the question (no gold SQL in Spider2).
WITH d AS (SELECT customer_id, txn_date, julianday(txn_date) AS jd,
                  SUM(CASE WHEN txn_type = 'deposit' THEN txn_amount ELSE -txn_amount END) AS v
           FROM customer_transactions GROUP BY 1, 2),
r AS (SELECT customer_id, txn_date, jd,
             SUM(v) OVER (PARTITION BY customer_id ORDER BY jd) AS bal,
             MIN(jd) OVER (PARTITION BY customer_id) AS j0,
             MIN(substr(txn_date, 1, 7)) OVER (PARTITION BY customer_id) AS m0 FROM d),
a AS (SELECT customer_id, txn_date, jd, j0, m0,
             AVG(bal) OVER (PARTITION BY customer_id ORDER BY jd
                            RANGE BETWEEN 29 PRECEDING AND CURRENT ROW) AS av FROM r),
mx AS (SELECT customer_id, substr(txn_date, 1, 7) AS m, MAX(MAX(av, 0)) AS best FROM a
       WHERE jd - j0 >= 29 AND substr(txn_date, 1, 7) > m0 GROUP BY 1, 2)
SELECT m AS month, ROUND(SUM(best), 3) AS total FROM mx GROUP BY m ORDER BY m;
