-- India salaries: events → source table (refdata rebuild, DuckDB).
-- Lakh grouping: the last 3 digits, then pairs. The head (all but the last 3 digits) is reversed,
-- a comma follows each pair, and it is reversed back; DuckDB's RE2 has no look-ahead.

-- table: SalaryDataset
WITH d AS (SELECT l.*, r.salaries_reported, r.salary_currency, r.salary_period,
                  CAST(r.salary_amount AS VARCHAR) AS digits
           FROM salary_listing l JOIN salary_aggregate_reported r USING (listing_id))
SELECT CAST(ext_id AS BIGINT) AS "index", company_name AS CompanyName, job_title AS JobTitle,
       CAST(salaries_reported AS DOUBLE) AS SalariesReported, location AS Location,
       salary_currency
       || CASE WHEN length(digits) <= 3 THEN digits
               ELSE ltrim(reverse(regexp_replace(reverse(left(digits, length(digits) - 3)),
                                                 '(\d\d)', '\1,', 'g')), ',')
                    || ',' || right(digits, 3) END
       || '/' || salary_period AS Salary
FROM d;
