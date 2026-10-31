-- local031: the highest monthly delivered-order volume in the year (2016-2018) with the
-- fewest delivered orders. Written from the question (no gold SQL); E_commerce names.
WITH d AS (SELECT substr(order_delivered_customer_date, 1, 4) AS y,
                  substr(order_delivered_customer_date, 1, 7) AS m
           FROM orders WHERE order_status = 'delivered'
             AND substr(order_delivered_customer_date, 1, 4) IN ('2016', '2017', '2018')),
low AS (SELECT y FROM d GROUP BY y ORDER BY COUNT(*), y LIMIT 1)
SELECT MAX(n) AS max_monthly FROM (SELECT m, COUNT(*) AS n FROM d WHERE y = (SELECT y FROM low)
                                   GROUP BY m);
