-- local049 (_b reading): average new unicorns per year in the top industry, 2019-2021.
-- Written from the question (no gold SQL); reproduces gold CSV _b, 57.666667: each table
-- deduplicated first, dates joined to industries (Fintech, 173 companies / 3). With local049
-- it checks that each duplicate marker lands on its own table.
WITH d AS (SELECT DISTINCT company_id, date_joined FROM companies_dates),
     i AS (SELECT DISTINCT company_id, industry FROM companies_industries),
     w AS (SELECT i.industry FROM d JOIN i USING (company_id)
           WHERE CAST(substr(d.date_joined, 1, 4) AS INT) BETWEEN 2019 AND 2021)
SELECT round(count(*) / 3.0, 6) AS avg_new_unicorns_per_year
FROM w GROUP BY industry ORDER BY count(*) DESC LIMIT 1;
