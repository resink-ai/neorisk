-- local168: remote Data Analyst postings with a non-null annual salary; their average salary
-- over the (posting, skill) rows of the cohort's three most frequent skill ids.
-- No gold SQL; written from the question (docs/research/spider2/jobpostings.md §0.1,
-- scripts/jobpostings/gold_168.py). Reproduces gold _a (92689.2222...): five skill ids tie at 3
-- postings, and the tie breaks by lowest skill_id, giving {0, 1, 5}; orphan skill ids count, as
-- skills_dim is not joined. Gold _b (96521.7109375) breaks the tie as {0, 1, 181}.
WITH c AS (SELECT p.job_id, p.salary_year_avg, s.skill_id
           FROM job_postings_fact p JOIN skills_job_dim s ON s.job_id = p.job_id
           WHERE p.job_title_short = 'Data Analyst' AND p.salary_year_avg IS NOT NULL
             AND p.job_work_from_home = 1),
top AS (SELECT skill_id FROM c GROUP BY skill_id ORDER BY count(*) DESC, skill_id LIMIT 3)
SELECT avg(salary_year_avg) AS overall_avg_salary
FROM c WHERE skill_id IN (SELECT skill_id FROM top);
