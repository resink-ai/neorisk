-- local253: top 5 companies by average salary in each of Mumbai, Pune, New Delhi and Hyderabad,
-- each beside the national average salary.
-- Written from the question: Spider2 has no gold SQL, only 3 gold CSVs with 3 different
-- cleaning rules. This reproduces variant local253_a: strip the non-numeric characters, annualise
-- /mo × 12 and /hr × 2,080, keep every currency, and take the national mean over all rows.
-- Companies tied on the average sort by name; NULL companies are not ranked.
WITH cleaned AS (
    SELECT Location, CompanyName,
           CAST(replace(replace(replace(replace(replace(replace(replace(replace(
               Salary, ',', ''), '₹', ''), '$', ''), '£', ''), 'AFN ', ''),
               '/yr', ''), '/mo', ''), '/hr', '') AS REAL)
           * CASE WHEN Salary LIKE '%/mo' THEN 12 WHEN Salary LIKE '%/hr' THEN 2080 ELSE 1 END
               AS salary
    FROM SalaryDataset
),
national AS (SELECT avg(salary) AS avg_country FROM cleaned),
by_company AS (
    SELECT Location, CompanyName, avg(salary) AS avg_state,
           row_number() OVER (PARTITION BY Location
                              ORDER BY avg(salary) DESC, CompanyName) AS rk
    FROM cleaned
    WHERE Location IN ('Mumbai', 'Pune', 'New Delhi', 'Hyderabad') AND CompanyName IS NOT NULL
    GROUP BY Location, CompanyName
)
SELECT b.Location, b.CompanyName AS "Company Name", b.avg_state AS "Average Salary in State",
       n.avg_country AS "Average Salary in Country"
FROM by_company b CROSS JOIN national n
WHERE b.rk <= 5
ORDER BY b.Location, b.rk;
