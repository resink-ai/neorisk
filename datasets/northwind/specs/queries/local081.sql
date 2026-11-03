-- local081: customers who ordered in 1998, their spend (unitprice × quantity, no discount) put in
-- customergroupthreshold's bands; count and share of customers per band.
-- Written from the question (no gold SQL); matches the gold CSV.
WITH s AS (
  SELECT o.customerid, sum(d.unitprice * d.quantity) AS spent
  FROM orders o JOIN order_details d USING (orderid)
  WHERE o.orderdate >= '1998-01-01' AND o.orderdate < '1999-01-01' GROUP BY 1),
g AS (
  SELECT s.customerid, t.groupname
  FROM s JOIN customergroupthreshold t ON s.spent BETWEEN t.rangebottom AND t.rangetop)
SELECT groupname, count(*) AS customer_count,
       round(100.0 * count(*) / (SELECT count(*) FROM s), 2) AS pct
FROM g GROUP BY 1
ORDER BY CASE groupname WHEN 'Low' THEN 1 WHEN 'Medium' THEN 2 WHEN 'High' THEN 3 ELSE 4 END;
