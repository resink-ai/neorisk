-- name: composition_quantiles
with s as (select composition v, row_number() over (order by composition) rn, count(*) over () n from interest_metrics)
select max(case when rn = cast(n*0.05 as int) then v end) p5, max(case when rn = cast(n*0.25 as int) then v end) p25, max(case when rn = cast(n*0.5 as int) then v end) p50,
       max(case when rn = cast(n*0.75 as int) then v end) p75, max(case when rn = cast(n*0.95 as int) then v end) p95, max(v) mx, round(avg(v), 3) mean from s;
-- name: index_value_quantiles
with s as (select index_value v, row_number() over (order by index_value) rn, count(*) over () n from interest_metrics)
select max(case when rn = cast(n*0.05 as int) then v end) p5, max(case when rn = cast(n*0.25 as int) then v end) p25, max(case when rn = cast(n*0.5 as int) then v end) p50,
       max(case when rn = cast(n*0.75 as int) then v end) p75, max(case when rn = cast(n*0.95 as int) then v end) p95, max(v) mx, round(avg(v), 3) mean from s;
-- name: composition_min_by_month
select coalesce(month_year,'NULL') my, min(composition), round(avg(composition),3) mean, max(composition), min(index_value), max(index_value) from interest_metrics group by 1 order by min(rowid);
-- name: index_value_ties
select count(*) rows_, count(distinct coalesce(month_year,'NULL') || '|' || index_value) distinct_month_index from interest_metrics;
-- name: month_to_month_persistence
-- interests present in month t that are present in month t+1
with p as (select interest_id, cast(_year*12 + _month as int) k from interest_metrics where month_year is not null)
select a.k, count(*) present, sum(exists (select 1 from p b where b.interest_id = a.interest_id and b.k = a.k + 1)) next_month from p a group by 1 order by 1;
-- name: month_lag_corr_inputs
-- same interest, consecutive months: ratio of composition
with p as (select interest_id, cast(_year*12 + _month as int) k, composition c, index_value i from interest_metrics where month_year is not null)
select count(*) pairs, round(avg(b.c / a.c), 4) mean_comp_ratio, round(avg(b.i / a.i), 4) mean_index_ratio,
       sum(abs(b.c / a.c - 1) <= 0.1) comp_within_10pct
from p a join p b on b.interest_id = a.interest_id and b.k = a.k + 1;
-- name: gaps_in_presence
-- interests whose months are not contiguous
with p as (select interest_id, min(cast(_year*12+_month as int)) lo, max(cast(_year*12+_month as int)) hi, count(*) n from interest_metrics where month_year is not null group by 1)
select sum(hi - lo + 1 = n) contiguous, sum(hi - lo + 1 > n) with_gaps, count(*) n from p;
-- name: first_month_of_interests
with p as (select interest_id, min(cast(_year*100+_month as int)) f from interest_metrics where month_year is not null group by 1)
select f, count(*) new_interests from p group by 1 order by 1;
