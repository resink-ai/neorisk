-- Unicorn companies: events → source tables (refdata rebuild, DuckDB). Each table is its base
-- rows, then one more copy of a row per source_row_duplicated marker on that table.

-- table: companies_funding
WITH f AS (SELECT CAST(c.ext_id AS BIGINT) AS company_id, s.company_id AS k, s.valuation,
                  s.funding, s.select_investors
           FROM companies_snapshot s JOIN companies c ON c.company_key = s.company_id)
SELECT company_id, valuation, funding, select_investors FROM f
UNION ALL
SELECT f.company_id, f.valuation, f.funding, f.select_investors
FROM source_row_duplicated d JOIN f ON f.k = d.company_id
WHERE d.src_table = 'companies_funding';

-- table: companies_dates
WITH t AS (SELECT company_key AS k, CAST(ext_id AS BIGINT) AS company_id,
                  strftime(created_at AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%S') || '.000'
                      AS date_joined,
                  year_founded
           FROM companies)
SELECT company_id, date_joined, year_founded FROM t
UNION ALL
SELECT t.company_id, t.date_joined, t.year_founded
FROM source_row_duplicated d JOIN t ON t.k = d.company_id
WHERE d.src_table = 'companies_dates';

-- table: companies_industries
WITH t AS (SELECT company_key AS k, CAST(ext_id AS BIGINT) AS company_id,
                  CAST(industry AS VARCHAR) AS industry
           FROM companies)
SELECT company_id, industry FROM t
UNION ALL
SELECT t.company_id, t.industry
FROM source_row_duplicated d JOIN t ON t.k = d.company_id
WHERE d.src_table = 'companies_industries';
