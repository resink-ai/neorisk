-- name: setup_indexes
create index ip on job_postings_fact(job_id); create index ipc on job_postings_fact(company_id);
create index ic on job_company(company_id); create index isj on skills_job_dim(job_id); create index iss on skills_job_dim(skill_id);
create index isk on skills_dim(skill_id);

-- name: key_uniqueness
select 'postings.job_id' k, count(*) n, count(distinct job_id) d from job_postings_fact
union all select 'company.company_id', count(*), count(distinct company_id) from job_company
union all select 'company.name', count(*), count(distinct name) from job_company
union all select 'skills.skill_id', count(*), count(distinct skill_id) from skills_dim
union all select 'skills_job.(job_id,skill_id)', count(*), count(distinct job_id||'|'||skill_id) from skills_job_dim;

-- name: exact_duplicate_rows
select (select count(*) from skills_job_dim) - (select count(*) from (select distinct job_id, skill_id from skills_job_dim)) dup_links;

-- name: postings_company_coverage
select count(*) postings, sum(c.company_id is not null) company_found,
  count(distinct p.company_id) distinct_companies, count(distinct c.company_id) distinct_found
from job_postings_fact p left join job_company c using(company_id);

-- name: company_used
select count(*) companies, sum(exists (select 1 from job_postings_fact p where p.company_id = c.company_id)) used from job_company c;

-- name: links_job_coverage
select count(*) links, sum(p.job_id is not null) job_found, count(distinct s.job_id) distinct_jobs,
  count(distinct case when p.job_id is not null then s.job_id end) distinct_jobs_found
from skills_job_dim s left join job_postings_fact p using(job_id);

-- name: links_skill_coverage
select count(*) links, sum(k.skill_id is not null) skill_found, count(distinct s.skill_id) distinct_skill_ids,
  count(distinct k.skill_id) distinct_found from skills_job_dim s left join skills_dim k using(skill_id);

-- name: links_both_found
select sum(p.job_id is not null and k.skill_id is not null) both_found, count(*) from skills_job_dim s
  left join job_postings_fact p using(job_id) left join skills_dim k using(skill_id);

-- name: postings_with_links
select count(*) postings, sum(exists (select 1 from skills_job_dim s where s.job_id = p.job_id)) with_any_link from job_postings_fact p;

-- name: skills_used
select count(*) skills, sum(exists (select 1 from skills_job_dim s where s.skill_id = k.skill_id)) used from skills_dim k;

-- name: id_ranges
select 'postings.job_id' c, min(job_id), max(job_id) from job_postings_fact
union all select 'links.job_id', min(job_id), max(job_id) from skills_job_dim
union all select 'postings.company_id', min(company_id), max(company_id) from job_postings_fact
union all select 'company.company_id', min(company_id), max(company_id) from job_company
union all select 'links.skill_id', min(skill_id), max(skill_id) from skills_job_dim
union all select 'skills.skill_id', min(skill_id), max(skill_id) from skills_dim;

-- name: sample_rate_guess
-- distinct ids: share of the id space present. Upstream ids look dense 0..max.
select (select count(*) from job_postings_fact)*1.0/(select max(job_id)+1 from job_postings_fact) postings_share,
  (select count(distinct job_id) from skills_job_dim)*1.0/(select max(job_id)+1 from skills_job_dim) links_job_share,
  (select count(*) from skills_dim)*1.0/(select max(skill_id)+1 from skills_job_dim) skills_share;

-- name: rowid_order
select 'postings' t, sum(job_id > pj) asc_pairs, count(pj) pairs from (select job_id, lag(job_id) over (order by rowid) pj from job_postings_fact)
union all select 'company', sum(company_id > pc), count(pc) from (select company_id, lag(company_id) over (order by rowid) pc from job_company)
union all select 'links', sum(job_id > pj or job_id = pj and skill_id > ps), count(pj) from (select job_id, skill_id, lag(job_id) over (order by rowid) pj, lag(skill_id) over (order by rowid) ps from skills_job_dim)
union all select 'skills', sum(skill_id > ps), count(ps) from (select skill_id, lag(skill_id) over (order by rowid) ps from skills_dim);

-- name: skill_types
select type, count(*), group_concat(skills, ', ') from skills_dim group by 1 order by 2 desc;
