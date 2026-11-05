-- name: row_counts
select 'interest_metrics' t, count(*) n from interest_metrics union all select 'interest_map', count(*) from interest_map;
-- name: typeof_metrics
select typeof(_month) m, typeof(_year) y, typeof(month_year) my, typeof(interest_id) iid, typeof(composition) c, typeof(index_value) iv,
       typeof(ranking) r, typeof(percentile_ranking) pr, count(*) n
from interest_metrics group by 1,2,3,4,5,6,7,8;
-- name: typeof_map
select typeof(id), typeof(interest_name), typeof(interest_summary), typeof(created_at), typeof(last_modified), count(*) n from interest_map group by 1,2,3,4,5;
-- name: metrics_null_patterns
select _month is null m_null, _year is null y_null, month_year is null my_null, interest_id is null iid_null, count(*) n
from interest_metrics group by 1,2,3,4;
-- name: metrics_null_rows_sample
select rowid, * from interest_metrics where month_year is null limit 5;
-- name: null_interest_id_rows
select rowid, * from interest_metrics where interest_id is null;
-- name: month_year_values
select month_year, _month, _year, count(*) n, count(distinct interest_id) ids, min(ranking), max(ranking) from interest_metrics group by 1, 2, 3 order by _year, _month;
-- name: month_year_consistency
select count(*) n, sum(month_year = printf('%02d-%d', cast(_month as int), cast(_year as int))) consistent from interest_metrics where month_year is not null;
-- name: key_uniqueness_metrics
select count(*) n, count(distinct month_year || '|' || interest_id) d from interest_metrics where month_year is not null;
-- name: key_uniqueness_map
select count(*) n, count(distinct id) d_id, count(distinct interest_name) d_name, min(id), max(id) from interest_map;
-- name: interest_id_integral
select count(*) n, sum(interest_id = cast(interest_id as integer)) integral from interest_metrics where interest_id is not null;
-- name: orphans_metrics_to_map
select count(*) rows_, count(distinct interest_id) ids from interest_metrics m where interest_id is not null and not exists (select 1 from interest_map p where p.id = m.interest_id);
-- name: orphan_ids
select interest_id, count(*), group_concat(coalesce(month_year,'NULL')) from interest_metrics m where interest_id is not null and not exists (select 1 from interest_map p where p.id = m.interest_id) group by 1;
-- name: map_ids_without_metrics
select count(*) n from interest_map p where not exists (select 1 from interest_metrics m where m.interest_id = p.id);
-- name: map_ids_only_in_null_month_rows
select count(*) n from interest_map p where exists (select 1 from interest_metrics m where m.interest_id = p.id)
  and not exists (select 1 from interest_metrics m where m.interest_id = p.id and m.month_year is not null);
-- name: duplicate_names
select interest_name, count(*), group_concat(id) from interest_map group by 1 having count(*) > 1;
-- name: map_text_formats
select sum(interest_name <> trim(interest_name)) name_untrimmed, sum(interest_summary is null) summ_null, sum(interest_summary = '') summ_empty,
       sum(interest_summary <> trim(interest_summary)) summ_untrimmed, sum(interest_name = '') name_empty,
       sum(created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]') created_fmt_ok,
       sum(last_modified glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]') modified_fmt_ok
from interest_map;
-- name: rowid_order_map
select count(*) n, sum(id > lag_id) increasing from (select id, lag(id) over (order by rowid) lag_id from interest_map) where lag_id is not null;
-- name: rowid_order_metrics
select count(*) pairs, sum(k >= lag_k) nondecreasing_month, sum(k = lag_k and ranking >= lag_r) rank_nondecreasing_in_month
from (select coalesce(_year*100+_month, 999999) k, ranking, lag(coalesce(_year*100+_month, 999999)) over (order by rowid) lag_k,
             lag(ranking) over (order by rowid) lag_r from interest_metrics) where lag_k is not null;
-- name: metrics_row_order_blocks
select rowid_block, min(rowid), max(rowid), month_year, count(*) from (
  select rowid, month_year, rowid - row_number() over (partition by coalesce(month_year,'NULL') order by rowid) rowid_block from interest_metrics)
group by rowid_block, month_year order by min(rowid) limit 30;
