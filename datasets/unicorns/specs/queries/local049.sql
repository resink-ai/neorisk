-- local049: average new unicorns per year in the top industry, 2019-2021.
-- Written from the question (no gold SQL); reproduces gold CSV _a, 60.333333: the raw rows of
-- all three tables joined, as the DataCamp project does, so Spider2's duplicates fan out
-- (Fintech, 181 rows / 3).
WITH w AS (SELECT i.industry
           FROM companies_dates d
           JOIN companies_industries i ON i.company_id = d.company_id
           JOIN companies_funding f ON f.company_id = d.company_id
           WHERE CAST(substr(d.date_joined, 1, 4) AS INT) BETWEEN 2019 AND 2021)
SELECT round(count(*) / 3.0, 6) AS average_new_unicorns_per_year
FROM w GROUP BY industry ORDER BY count(*) DESC LIMIT 1;
