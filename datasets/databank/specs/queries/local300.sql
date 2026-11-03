-- local300: daily balance for every day between a customer's first and last transaction
-- (carried forward), negatives as 0; per customer the monthly max; summed per month.
-- Written from the question; matches the research reproduction (scripts/a_databank2.py).
WITH RECURSIVE
d AS (SELECT customer_id, txn_date,
             SUM(CASE WHEN txn_type = 'deposit' THEN txn_amount ELSE -txn_amount END) AS v
      FROM customer_transactions GROUP BY 1, 2),
span AS (SELECT customer_id, MIN(txn_date) AS d0, MAX(txn_date) AS d1 FROM d GROUP BY 1),
days(customer_id, day, d1) AS (
  SELECT customer_id, d0, d1 FROM span
  UNION ALL SELECT customer_id, date(day, '+1 day'), d1 FROM days WHERE day < d1),
bal AS (SELECT days.customer_id, days.day,
               SUM(COALESCE(d.v, 0)) OVER (PARTITION BY days.customer_id ORDER BY days.day) AS b
        FROM days LEFT JOIN d ON d.customer_id = days.customer_id AND d.txn_date = days.day)
SELECT m AS month, SUM(best) AS total
FROM (SELECT customer_id, substr(day, 1, 7) AS m, MAX(MAX(b, 0)) AS best FROM bal GROUP BY 1, 2)
GROUP BY m ORDER BY m;
