-- local028: delivered orders per month (rows) for 2016, 2017, 2018 (columns), by the month
-- of delivery to the customer (the research reproduces the gold values this way).
-- Written from the question (no gold SQL); E_commerce names.
WITH m(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM m WHERE n < 12),
d AS (SELECT CAST(substr(order_delivered_customer_date, 1, 4) AS INTEGER) AS y,
             CAST(substr(order_delivered_customer_date, 6, 2) AS INTEGER) AS mo
      FROM orders WHERE order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL)
SELECT m.n AS month, SUM(d.y = 2016) AS y2016, SUM(d.y = 2017) AS y2017, SUM(d.y = 2018) AS y2018
FROM m LEFT JOIN d ON d.mo = m.n GROUP BY m.n ORDER BY m.n;
