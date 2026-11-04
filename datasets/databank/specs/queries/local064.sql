-- local064: per customer and month of 2020, deposits minus withdrawals; the months with the
-- most and fewest customers in the positive; difference of those months' average balances.
-- Written from the question (no gold SQL). Gold (557.70) also counts months with no data, e.g. May.
WITH net AS (
  SELECT customer_id, substr(txn_date, 1, 7) AS m,
         SUM(CASE txn_type WHEN 'deposit' THEN txn_amount
                           WHEN 'withdrawal' THEN -txn_amount ELSE 0 END) AS bal
  FROM customer_transactions WHERE txn_date LIKE '2020-%' GROUP BY 1, 2),
cnt AS (SELECT m, SUM(bal > 0) AS pos, AVG(bal) AS avg_bal FROM net GROUP BY m)
SELECT (SELECT avg_bal FROM cnt ORDER BY pos DESC, m LIMIT 1)
     - (SELECT avg_bal FROM cnt ORDER BY pos ASC, m LIMIT 1) AS diff;
