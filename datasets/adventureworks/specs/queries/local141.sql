-- local141: per salesperson and year, total sales (sum of totaldue) against the summed quarterly
-- quotas, and the difference. Written from the question (no gold SQL); matches gold CSV _b
-- (58 rows); _a (62 rows) adds a yearly row for the orders with no salesperson.
WITH s AS (
  SELECT salespersonid AS sp, CAST(strftime('%Y', orderdate) AS INT) AS y, sum(totaldue) AS total
  FROM salesorderheader WHERE salespersonid <> '' GROUP BY 1, 2),
q AS (
  SELECT BusinessEntityID AS sp, CAST(strftime('%Y', QuotaDate) AS INT) AS y,
         sum(SalesQuota) AS quota
  FROM SalesPersonQuotaHistory GROUP BY 1, 2)
SELECT s.sp, s.y, s.total, q.quota, s.total - q.quota AS diff
FROM s JOIN q USING (sp, y) ORDER BY 1, 2;
