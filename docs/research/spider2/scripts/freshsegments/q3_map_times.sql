-- name: created_modified_order
select sum(last_modified > created_at) modified_after, sum(last_modified = created_at) same, sum(last_modified < created_at) modified_before, count(*) n from interest_map;
-- name: created_range
select min(created_at), max(created_at), min(last_modified), max(last_modified) from interest_map;
-- name: created_by_month
select substr(created_at, 1, 7) ym, count(*) n from interest_map group by 1 order by 1;
-- name: modified_by_month
select substr(last_modified, 1, 7) ym, count(*) n from interest_map group by 1 order by 1;
-- name: distinct_stamps
select count(distinct created_at) created_stamps, count(distinct last_modified) modified_stamps from interest_map;
-- name: top_created_stamps
select created_at, count(*) n from interest_map group by 1 order by 2 desc limit 8;
-- name: first_metric_vs_created
-- metric month (first day) vs the interest's created_at
with f as (select interest_id, min(_year * 100 + _month) ym from interest_metrics where month_year is not null group by 1)
select sum(printf('%04d-%02d-01', ym / 100, ym % 100) < substr(m.created_at, 1, 10)) first_metric_month_before_created_day,
       sum(printf('%04d-%02d-01', ym / 100, ym % 100) >= substr(m.created_at, 1, 10)) ok, count(*) n
from f join interest_map m on m.id = f.interest_id;
-- name: metric_rows_before_created
select count(*) rows_ , count(distinct interest_id) ids,
       sum(substr(m.created_at, 1, 7) = printf('%04d-%02d', cast(_year as int), cast(_month as int))) created_in_same_month
from interest_metrics x join interest_map m on m.id = x.interest_id
where x.month_year is not null and printf('%04d-%02d-01', cast(_year as int), cast(_month as int)) < substr(m.created_at, 1, 10);
-- name: metric_rows_before_created_month_end
-- same test against the month's end: is the metric month entirely before creation?
select count(*) rows_ from interest_metrics x join interest_map m on m.id = x.interest_id
where x.month_year is not null and date(printf('%04d-%02d-01', cast(_year as int), cast(_month as int)), '+1 month') <= substr(m.created_at, 1, 10);
-- name: months_per_interest
select months, count(*) interests from (select interest_id, count(distinct month_year) months from interest_metrics where month_year is not null group by 1) group by 1 order by 1;
-- name: id_vs_created_order
select count(*) pairs, sum(created_at >= lag_c) nondecreasing from (select created_at, lag(created_at) over (order by id) lag_c from interest_map) where lag_c is not null;
-- name: id_ranges
select case when id < 1000 then '<1000' when id < 10000 then '1000-9999' when id < 40000 then '10000-39999' else '>=40000' end b, count(*), min(created_at), max(created_at) from interest_map group by 1;
-- name: summaries_untrimmed
select id, '[' || interest_summary || ']' s from interest_map where interest_summary <> trim(interest_summary);
-- name: map_unused
select id, interest_name, created_at from interest_map p where not exists (select 1 from interest_metrics m where m.interest_id = p.id);
-- name: non_ascii
select count(*) from interest_map where interest_name glob '*[^ -~]*' or interest_summary glob '*[^ -~]*';
