-- Job postings: events → source tables (refdata rebuild, DuckDB). Each table is a straight
-- projection; the salaries pass through as REAL.

-- table: job_postings_fact
SELECT job_id, company_id, job_title_short, job_title, job_location, job_via,
       job_schedule_type, job_work_from_home, search_location,
       strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS job_posted_date,
       job_no_degree_mention, job_health_insurance, job_country, salary_rate, salary_year_avg,
       salary_hour_avg
FROM job_posted;

-- table: job_company
SELECT CAST(ext_id AS BIGINT) AS company_id, name, link, link_google, thumbnail FROM companies;

-- table: skills_dim
SELECT CAST(ext_id AS BIGINT) AS skill_id, skills, type FROM skills;

-- table: skills_job_dim
SELECT job_id, skill_id FROM job_skills;
