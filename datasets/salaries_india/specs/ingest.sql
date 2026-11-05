-- India salaries: source table → events (refdata ingest). Untimed: everything is at the rule
-- time 2022-01-01. Salary is '<currency><digits with commas>/<yr|mo|hr>'; the currency is one
-- character, or 'AFN '.

-- entity: salary_listing
SELECT CAST("index" AS TEXT) AS ext_id, CompanyName AS company_name, JobTitle AS job_title,
       Location AS location, '2022-01-01 00:00:00' AS created_at
FROM SalaryDataset ORDER BY "index";

-- event: salary_aggregate_reported owner=listing_id ord=k
SELECT '2022-01-01 00:00:00' AS event_time, CAST("index" AS TEXT) AS listing_id,
       CAST(SalariesReported AS INTEGER) AS salaries_reported, cur AS salary_currency,
       CAST(replace(substr(Salary, length(cur) + 1, instr(Salary, '/') - length(cur) - 1), ',', '')
            AS INTEGER) AS salary_amount,
       substr(Salary, instr(Salary, '/') + 1) AS salary_period, "index" AS k
FROM (SELECT *, CASE WHEN Salary LIKE 'AFN %' THEN 'AFN ' ELSE substr(Salary, 1, 1) END AS cur
      FROM SalaryDataset)
ORDER BY "index";
