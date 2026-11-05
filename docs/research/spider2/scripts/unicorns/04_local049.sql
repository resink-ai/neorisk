-- Run: sqlite3 -readonly data/spider2/modern_data.sqlite < docs/research/spider2/scripts/unicorns/04_local049.sql
-- local049: average new unicorns per year in the top industry, 2019-2021.
-- Gold CSVs: _a = 60.333333, _b = 57.666667. No gold SQL. Readings tried below.
.headers on
.mode list
.print ## R1: join dates x industries on company_id over raw rows (duplicates fan out), top industry by 2019-2021 count
WITH j AS (SELECT i.industry, CAST(substr(d.date_joined,1,4) AS INT) y FROM companies_dates d JOIN companies_industries i ON i.company_id=d.company_id),
w AS (SELECT * FROM j WHERE y BETWEEN 2019 AND 2021),
top AS (SELECT industry FROM w GROUP BY 1 ORDER BY count(*) DESC LIMIT 1)
SELECT (SELECT industry FROM top) top, count(*) n, round(count(*)/3.0, 6) avg_per_year FROM w WHERE industry=(SELECT industry FROM top);
.print ## R2: distinct companies (dedup each table first), top by 2019-2021
WITH d AS (SELECT DISTINCT company_id, date_joined FROM companies_dates), i AS (SELECT DISTINCT company_id, industry FROM companies_industries),
w AS (SELECT i.industry, CAST(substr(d.date_joined,1,4) AS INT) y FROM d JOIN i USING (company_id) WHERE y BETWEEN 2019 AND 2021),
top AS (SELECT industry FROM w GROUP BY 1 ORDER BY count(*) DESC LIMIT 1)
SELECT (SELECT industry FROM top) top, count(*) n, round(count(*)/3.0, 6) avg_per_year FROM w WHERE industry=(SELECT industry FROM top);
.print ## per-year counts in top industry (Fintech), raw join vs dedup
SELECT y, sum(raw) raw, sum(dd) dedup FROM (
  SELECT CAST(substr(d.date_joined,1,4) AS INT) y, 1 raw, 0 dd FROM companies_dates d JOIN companies_industries i ON i.company_id=d.company_id WHERE i.industry='Fintech'
  UNION ALL
  SELECT CAST(substr(d.date_joined,1,4) AS INT), 0, 1 FROM (SELECT DISTINCT company_id, date_joined FROM companies_dates) d JOIN (SELECT DISTINCT company_id, industry FROM companies_industries) i USING (company_id) WHERE i.industry='Fintech')
WHERE y BETWEEN 2019 AND 2021 GROUP BY y;
.print ## top 3 industries 2019-2021 (dedup)
SELECT i.industry, count(*) FROM (SELECT DISTINCT company_id, date_joined FROM companies_dates) d JOIN (SELECT DISTINCT company_id, industry FROM companies_industries) i USING (company_id)
WHERE CAST(substr(d.date_joined,1,4) AS INT) BETWEEN 2019 AND 2021 GROUP BY 1 ORDER BY 2 DESC LIMIT 3;
.print ## R3: also join companies_funding (raw rows, as the DataCamp project does)
WITH w AS (SELECT i.industry FROM companies_dates d JOIN companies_industries i ON i.company_id=d.company_id JOIN companies_funding f ON f.company_id=d.company_id
  WHERE CAST(substr(d.date_joined,1,4) AS INT) BETWEEN 2019 AND 2021)
SELECT industry, count(*) n, round(count(*)/3.0, 6) avg_per_year FROM w GROUP BY 1 ORDER BY 2 DESC LIMIT 1;
