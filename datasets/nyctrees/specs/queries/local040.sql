-- local040: top 3 boroughs by tree count after joining trees to income by ZIP (median and mean
-- income > 0, a valid borough), with each one's average mean income.
-- Written from the question (no gold SQL); reproduces gold CSV _c exactly: raw trees, injected
-- copies included, joined to SELECT DISTINCT income_trees. "Filling missing ZIPs" is a no-op on
-- this copy (no NULL or 0 zipcode).
SELECT t.boroname AS borough, count(*) AS tree_count,
       avg(i.Estimate_Mean_income) AS average_mean_income
FROM trees t JOIN (SELECT DISTINCT * FROM income_trees) i ON i.zipcode = t.zipcode
WHERE i.Estimate_Median_income > 0 AND i.Estimate_Mean_income > 0
  AND t.boroname IS NOT NULL AND t.boroname <> ''
GROUP BY t.boroname ORDER BY tree_count DESC LIMIT 3;
