-- local114: per region, the number of orders, total sales, and the top sales rep(s) by sales
-- amount, ties included.
-- Written from the question (no gold SQL); reproduces gold variants local114_a/_b/_c.csv
-- exactly (they differ only in text formatting; this returns the rep and amount as separate
-- columns). From the report's scripts/parchposey/q2_values.sql block gold_local114.
WITH r AS (
    SELECT g.name AS region, s.name AS rep, sum(o.total_amt_usd) AS amt, count(*) AS n
    FROM web_orders o JOIN web_accounts a ON a.id = o.account_id
        JOIN web_sales_reps s ON s.id = a.sales_rep_id JOIN web_region g ON g.id = s.region_id
    GROUP BY 1, 2
),
t AS (SELECT region, sum(n) AS orders, sum(amt) AS total FROM r GROUP BY 1),
m AS (SELECT region, max(amt) AS mx FROM r GROUP BY 1)
SELECT t.region, t.orders, t.total, r.rep, r.amt
FROM t JOIN m USING (region) JOIN r ON r.region = t.region AND r.amt = m.mx
ORDER BY 1;
