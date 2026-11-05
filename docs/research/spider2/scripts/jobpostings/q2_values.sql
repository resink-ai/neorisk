-- name: setup_indexes
create index ip on job_postings_fact(job_id); create index ipc on job_postings_fact(company_id);
create index ic on job_company(company_id); create index isj on skills_job_dim(job_id); create index iss on skills_job_dim(skill_id);

-- name: posted_date_format
select sum(job_posted_date glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]') iso_sec,
  sum(datetime(job_posted_date) = job_posted_date) valid, count(*) n, min(job_posted_date), max(job_posted_date) from job_postings_fact;

-- name: posted_by_month
select substr(job_posted_date,1,7) m, count(*) from job_postings_fact group by 1 order by 1;

-- name: posted_seconds
select sum(substr(job_posted_date,18,2) = '00') sec00, sum(substr(job_posted_date,15,5) = '00:00') minsec00, count(*) n from job_postings_fact;

-- name: posted_hour
select substr(job_posted_date,12,2) h, count(*) from job_postings_fact group by 1 order by 1;

-- name: duplicate_timestamps
select count(*) n_rows, count(distinct job_posted_date) distinct_ts from job_postings_fact;

-- name: title_short
select job_title_short, count(*), sum(salary_year_avg is not null) with_year_salary, round(avg(salary_year_avg)) avg_year from job_postings_fact group by 1 order by 2 desc;

-- name: salary_rate_vs_columns
select salary_rate, count(*), sum(salary_year_avg is not null) year_set, sum(salary_hour_avg is not null) hour_set from job_postings_fact group by 1 order by 2 desc;

-- name: salary_cents_grid
select sum(salary_year_avg*100 <> cast(salary_year_avg*100 as int)) year_off_cent_grid, sum(salary_year_avg <> cast(salary_year_avg as int)) year_non_integer, count(salary_year_avg),
  sum(salary_hour_avg*100 <> cast(round(salary_hour_avg*100) as int)) hour_off_cent_grid, sum(salary_hour_avg <> cast(salary_hour_avg as int)) hour_non_integer, count(salary_hour_avg) from job_postings_fact;

-- name: salary_hour_decimals
select length(cast(salary_hour_avg as text)) - instr(cast(salary_hour_avg as text), '.') decimals, count(*) from job_postings_fact where salary_hour_avg is not null group by 1;

-- name: salary_year_decimals
select length(cast(salary_year_avg as text)) - instr(cast(salary_year_avg as text), '.') decimals, count(*) from job_postings_fact where salary_year_avg is not null group by 1;

-- name: salary_float_noise
select salary_year_avg, printf('%.17g', salary_year_avg) from job_postings_fact where salary_year_avg <> round(salary_year_avg, 2) limit 10;

-- name: salary_hour_examples
select salary_hour_avg, printf('%.17g', salary_hour_avg), count(*) from job_postings_fact where salary_hour_avg <> round(salary_hour_avg, 2) group by 1 limit 10;

-- name: booleans
select sum(job_work_from_home) wfh, sum(job_no_degree_mention) no_degree, sum(job_health_insurance) health, count(*) n from job_postings_fact;

-- name: wfh_vs_location
select job_work_from_home, job_location, count(*) from job_postings_fact where job_location in ('Anywhere') or job_work_from_home = 1 group by 1,2 order by 3 desc limit 6;

-- name: via_prefix
select case when job_via like 'via %' then 'via ' when job_via is null then 'NULL' else substr(job_via,1,instr(job_via,' ')) end prefix, count(*) from job_postings_fact group by 1 order by 2 desc limit 12;

-- name: via_top
select job_via, count(*) from job_postings_fact group by 1 order by 2 desc limit 8;

-- name: schedule
select job_schedule_type, count(*) from job_postings_fact group by 1 order by 2 desc limit 10;

-- name: country_vs_search
select sum(job_country = search_location) same, sum(job_country <> search_location) diff, sum(job_country is null) null_country, count(*) from job_postings_fact;

-- name: search_location_top
select search_location, count(*) from job_postings_fact group by 1 order by 2 desc limit 8;

-- name: country_top
select job_country, count(*) from job_postings_fact group by 1 order by 2 desc limit 8;

-- name: title_whitespace
select job_id, '['||job_title||']' from job_postings_fact where job_title <> trim(job_title);

-- name: null_title
select job_id, job_title_short, job_title, job_posted_date from job_postings_fact where job_title is null;

-- name: company_text
select sum(link is null) link_null, sum(thumbnail is null) thumb_null, sum(link_google is null) lg_null,
  sum(link_google like 'https://www.google.com/search?%') lg_google, count(*) from job_company;

-- name: company_link_google_contains_name
select sum(instr(link_google, replace(name,' ','+')) > 0) contains_name_plus, count(link_google) from job_company;

-- name: postings_per_company
select n, count(*) companies from (select company_id, count(*) n from job_postings_fact group by 1) group by 1 order by 1 limit 12;

-- name: postings_per_company_max
select company_id, count(*) n from job_postings_fact group by 1 order by 2 desc limit 5;

-- name: skills_per_job_in_links
select n, count(*) jobs from (select job_id, count(*) n from skills_job_dim group by 1) group by 1 order by 1 limit 15;

-- name: skills_per_matched_job
select n, count(*) jobs from (select s.job_id, count(*) n from skills_job_dim s join job_postings_fact p using(job_id) group by 1) group by 1 order by 1 limit 15;

-- name: link_skill_freq_top
select s.skill_id, k.skills, count(*) from skills_job_dim s left join skills_dim k using(skill_id) group by 1 order by 3 desc limit 12;

-- name: link_skill_found_freq
select k.skills, k.type, count(*) from skills_job_dim s join skills_dim k using(skill_id) group by 1 order by 3 desc;
