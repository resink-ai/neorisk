-- local168: Data Analyst, salary_year_avg not null, remote; average salary over the top-3 most demanded skills.
-- name: setup_indexes
create index isj on skills_job_dim(job_id); create index iss on skills_job_dim(skill_id);

-- name: cohort
select count(*) postings from job_postings_fact where job_title_short = 'Data Analyst' and salary_year_avg is not null and job_work_from_home = 1;

-- name: cohort_skills_raw
-- skill frequency over the cohort, by skill_id (skills_dim may not have the row)
select s.skill_id, k.skills, count(*) n from job_postings_fact p join skills_job_dim s using(job_id) left join skills_dim k using(skill_id)
where p.job_title_short = 'Data Analyst' and p.salary_year_avg is not null and p.job_work_from_home = 1
group by 1 order by 3 desc, 1 limit 8;

-- name: local168_inner_join
-- top 3 skills (inner join to skills_dim), then the average salary over postings x top-skill rows
with c as (select * from job_postings_fact where job_title_short = 'Data Analyst' and salary_year_avg is not null and job_work_from_home = 1),
t as (select s.skill_id from c join skills_job_dim s using(job_id) join skills_dim k using(skill_id) group by 1 order by count(*) desc limit 3)
select avg(c.salary_year_avg) over_rows, count(*) n_rows,
  (select avg(salary_year_avg) from c where job_id in (select job_id from skills_job_dim where skill_id in (select skill_id from t))) over_distinct_postings
from c join skills_job_dim s using(job_id) where s.skill_id in (select skill_id from t);
