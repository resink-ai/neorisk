-- local297: monthly net (deposits +, withdrawals -), cumulative closing balance; share of
-- customers whose latest month grew by more than 5% (previous balance 0: growth = balance x 100).
-- Written from the question (no gold SQL in Spider2).
WITH net AS (
  SELECT customer_id, substr(txn_date, 1, 7) || '-01' AS m,
         SUM(CASE txn_type WHEN 'deposit' THEN txn_amount
                           WHEN 'withdrawal' THEN -txn_amount ELSE 0 END) AS n
  FROM customer_transactions GROUP BY 1, 2),
bal AS (SELECT customer_id, m, SUM(n) OVER (PARTITION BY customer_id ORDER BY m) AS b,
               ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY m DESC) AS rk FROM net),
g AS (SELECT cur.customer_id,
             CASE WHEN prev.b = 0 THEN cur.b * 100.0
                  ELSE (cur.b - prev.b) * 100.0 / prev.b END AS rate
      FROM bal cur JOIN bal prev ON prev.customer_id = cur.customer_id AND prev.rk = 2
      WHERE cur.rk = 1)
SELECT ROUND(100.0 * SUM(rate > 5) / COUNT(*), 2) AS pct FROM g;
