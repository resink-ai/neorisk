-- Job postings: source tables → events (refdata ingest). Ids are raw integers: about 90% of
-- them point at rows Spider's sampling dropped. The catalog start, 2022-12-31 06:03:30, is the
-- first posting.

-- entity: companies
-- Created at the company's first posting, else at the catalog start (rules).
SELECT CAST(c.company_id AS TEXT) AS ext_id, c.name,
       coalesce(f.first_posted, '2022-12-31 06:03:30') AS created_at
FROM job_company c
LEFT JOIN (SELECT company_id, min(job_posted_date) AS first_posted FROM job_postings_fact
           GROUP BY company_id) f USING (company_id)
ORDER BY c.company_id;

-- event: companies_snapshot owner=company_key
-- One per company at N = 2023-12-31 03:18:00, the last posting.
SELECT '2023-12-31 03:18:00' AS event_time, CAST(company_id AS TEXT) AS company_key, link,
       link_google, thumbnail
FROM job_company ORDER BY company_id;

-- entity: skills
-- No time exists: created at the catalog start (a rule).
SELECT CAST(skill_id AS TEXT) AS ext_id, skills, type, '2022-12-31 06:03:30' AS created_at
FROM skills_dim ORDER BY skill_id;

-- entity: job_skills
-- Created at its posting, else at the catalog start (rules).
SELECT s.job_id || '-' || s.skill_id AS ext_id, s.job_id, s.skill_id,
       coalesce(p.job_posted_date, '2022-12-31 06:03:30') AS created_at
FROM skills_job_dim s LEFT JOIN job_postings_fact p USING (job_id)
ORDER BY s.job_id, s.skill_id;

-- event: job_posted owner=job_id ord=job_id
SELECT iso_time(job_posted_date, '%Y-%m-%d %H:%M:%S') AS event_time, job_id, company_id,
       job_title_short, job_title, job_location, job_via, job_schedule_type, job_work_from_home,
       search_location, job_no_degree_mention, job_health_insurance, job_country, salary_rate,
       salary_year_avg, salary_hour_avg
FROM job_postings_fact ORDER BY job_id;
