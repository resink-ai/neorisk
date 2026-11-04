-- name: row_counts
SELECT 'SalaryDataset' t, count(*) n FROM SalaryDataset UNION ALL SELECT 'StaffHours', count(*) FROM StaffHours;
-- name: salary_typeof
SELECT typeof("index") i, typeof(CompanyName) c, typeof(JobTitle) j, typeof(SalariesReported) sr, typeof(Location) l, typeof(Salary) s, count(*) n FROM SalaryDataset GROUP BY 1,2,3,4,5,6;
-- name: salary_nulls
SELECT sum(CompanyName IS NULL) company, sum(JobTitle IS NULL) job, sum(SalariesReported IS NULL) reported, sum(Location IS NULL) loc, sum(Salary IS NULL) sal, sum(CompanyName='') company_empty FROM SalaryDataset;
-- name: null_reported_rows
SELECT * FROM SalaryDataset WHERE SalariesReported IS NULL;
-- name: index_vs_rowid
SELECT sum("index" <> rowid - 1) mism, min("index"), max("index") FROM SalaryDataset;
-- name: salary_format_mix
SELECT substr(Salary,1,1) cur, CASE WHEN Salary LIKE '%/yr' THEN 'yr' WHEN Salary LIKE '%/mo' THEN 'mo' WHEN Salary LIKE '%/hr' THEN 'hr' ELSE 'other' END per, count(*) n FROM SalaryDataset GROUP BY 1,2 ORDER BY 3 DESC;
-- name: salary_currency_samples
SELECT Salary, count(*) n FROM SalaryDataset WHERE Salary NOT LIKE '₹%' GROUP BY 1 LIMIT 10;
-- name: indian_digit_grouping
-- lakh grouping: ##,##,### ; count values whose comma pattern is not lakh style
SELECT count(*) n FROM SalaryDataset WHERE Salary LIKE '₹%/yr' AND replace(replace(Salary,'₹',''),'/yr','') NOT GLOB '[0-9]*' ;
-- name: duplicates
SELECT count(*) - (SELECT count(*) FROM (SELECT DISTINCT CompanyName, JobTitle, SalariesReported, Location, Salary FROM SalaryDataset)) full_dups,
       count(*) - (SELECT count(*) FROM (SELECT DISTINCT CompanyName, JobTitle, Location FROM SalaryDataset)) key_dups FROM SalaryDataset;
-- name: dup_examples
SELECT CompanyName, JobTitle, Location, count(*) n, group_concat(Salary, ' | ') s FROM SalaryDataset GROUP BY 1,2,3 HAVING n > 1 LIMIT 8;
-- name: job_title_mix
SELECT JobTitle, count(*) n FROM SalaryDataset GROUP BY 1 ORDER BY 2 DESC LIMIT 12;
-- name: job_titles
SELECT count(DISTINCT JobTitle) titles, count(DISTINCT CompanyName) companies FROM SalaryDataset;
-- name: reported_dist
SELECT CASE WHEN SalariesReported = 1 THEN '1' WHEN SalariesReported <= 5 THEN '2-5' WHEN SalariesReported <= 20 THEN '6-20' ELSE '21+' END b, count(*) n FROM SalaryDataset WHERE SalariesReported IS NOT NULL GROUP BY 1;
-- name: reported_integral
SELECT sum(SalariesReported = CAST(SalariesReported AS INT)) integral, count(SalariesReported) n FROM SalaryDataset;
-- name: rowid_sort
-- is the file sorted by (JobTitle block, Location, SalariesReported desc)?
SELECT count(*) runs FROM (SELECT JobTitle||Location k, lag(JobTitle||Location) OVER (ORDER BY rowid) p FROM SalaryDataset) WHERE p IS NULL OR p <> k;
-- name: rowid_reported_desc_within_runs
SELECT sum(nr > r) asc_steps, count(*) pairs FROM (SELECT SalariesReported r, JobTitle||Location k, lead(SalariesReported) OVER (ORDER BY rowid) nr, lead(JobTitle||Location) OVER (ORDER BY rowid) nk FROM SalaryDataset) WHERE nk = k;
-- name: whitespace
SELECT sum(CompanyName <> trim(CompanyName)) company_ws, sum(JobTitle <> trim(JobTitle)) job_ws FROM SalaryDataset;
-- name: gold_local253_strip_digits
-- clean = keep digits only; average per (Location, Company); country = average over all rows
WITH c AS (SELECT Location, CompanyName, CAST(replace(replace(replace(replace(replace(Salary,'₹',''),',',''),'/yr',''),'/mo',''),'/hr','') AS REAL) s FROM SalaryDataset),
n AS (SELECT avg(s) nat FROM c),
l AS (SELECT Location, CompanyName, avg(s) av, row_number() OVER (PARTITION BY Location ORDER BY avg(s) DESC) rk FROM c WHERE Location IN ('Mumbai','Pune','New Delhi','Hyderabad') GROUP BY 1,2)
SELECT Location, CompanyName, printf('%.6f', av) av, printf('%.6f', nat) nat FROM l, n WHERE rk <= 5 ORDER BY 1, rk;
-- name: national_avg_variants
WITH c AS (SELECT Location, CompanyName, Salary, CAST(replace(replace(replace(replace(replace(Salary,'₹',''),',',''),'/yr',''),'/mo',''),'/hr','') AS REAL) s FROM SalaryDataset)
SELECT 'all rows' v, printf('%.6f', avg(s)) a FROM c UNION ALL
SELECT 'avg of company avgs', printf('%.6f', avg(x)) FROM (SELECT CompanyName, avg(s) x FROM c GROUP BY 1) UNION ALL
SELECT 'avg of (loc,company) avgs', printf('%.6f', avg(x)) FROM (SELECT Location, CompanyName, avg(s) x FROM c GROUP BY 1,2) UNION ALL
SELECT 'only /yr rows', printf('%.6f', avg(s)) FROM c WHERE Salary LIKE '%/yr' UNION ALL
SELECT 'only rupee rows', printf('%.6f', avg(s)) FROM c WHERE Salary LIKE '₹%' UNION ALL
SELECT 'four cities', printf('%.6f', avg(s)) FROM c WHERE Location IN ('Mumbai','Pune','New Delhi','Hyderabad');
-- name: meta_rank
-- why does gold_a rank Meta 1st in Hyderabad while gold_b/c lack it?
SELECT * FROM SalaryDataset WHERE CompanyName = 'Meta' AND Location = 'Hyderabad';
-- name: location_mix
SELECT Location, count(*) n, round(count(*)*100.0/(SELECT count(*) FROM SalaryDataset),1) pct FROM SalaryDataset GROUP BY 1 ORDER BY 2 DESC;
