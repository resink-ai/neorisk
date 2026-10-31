-- name: fd_ids
-- is each *_id a function of its description, and vice versa?
select 'week_ending_day -> id' fd, count(*) groups, sum(n>1) violating from (select count(distinct week_ending_day_id) n from times group by week_ending_day)
union all select 'week_ending_day_id -> day', count(*), sum(n>1) from (select count(distinct week_ending_day) n from times group by week_ending_day_id)
union all select 'cal_month_desc -> id', count(*), sum(n>1) from (select count(distinct calendar_month_id) n from times group by calendar_month_desc)
union all select 'cal_month_id -> desc', count(*), sum(n>1) from (select count(distinct calendar_month_desc) n from times group by calendar_month_id)
union all select 'fis_month_desc -> id', count(*), sum(n>1) from (select count(distinct fiscal_month_id) n from times group by fiscal_month_desc)
union all select 'fis_month_id -> desc', count(*), sum(n>1) from (select count(distinct fiscal_month_desc) n from times group by fiscal_month_id)
union all select 'cal_q_desc -> id', count(*), sum(n>1) from (select count(distinct calendar_quarter_id) n from times group by calendar_quarter_desc)
union all select 'fis_q_desc -> id', count(*), sum(n>1) from (select count(distinct fiscal_quarter_id) n from times group by fiscal_quarter_desc)
union all select 'cal_year -> id', count(*), sum(n>1) from (select count(distinct calendar_year_id) n from times group by calendar_year)
union all select 'fis_year -> id', count(*), sum(n>1) from (select count(distinct fiscal_year_id) n from times group by fiscal_year);
-- name: week_ending_ids
select week_ending_day, group_concat(distinct week_ending_day_id), count(*) from times group by week_ending_day order by week_ending_day limit 12;
-- name: week_ending_id_count
select count(distinct week_ending_day) n_weeks, count(distinct week_ending_day_id) n_ids, min(week_ending_day_id), max(week_ending_day_id) from times;
-- name: id_tables
select 'cal_month' k, calendar_month_desc d, calendar_month_id id from times group by 2 having d in ('2019-01','2019-02','2019-12','2020-01','2023-12')
union all select 'fis_month', fiscal_month_desc, fiscal_month_id from times group by 2 having fiscal_month_desc in ('2019-01','2019-02','2019-12','2020-01','2023-12')
union all select 'cal_q', calendar_quarter_desc, calendar_quarter_id from times group by 2
union all select 'fis_q', fiscal_quarter_desc, fiscal_quarter_id from times group by 2
union all select 'cal_y', calendar_year, calendar_year_id from times group by 2
union all select 'fis_y', fiscal_year, fiscal_year_id from times group by 2;
-- name: fiscal_months
select fiscal_year, fiscal_month_number, fiscal_month_desc, min(time_id), max(time_id), count(*) n, group_concat(distinct days_in_fis_month) dim, group_concat(distinct end_of_fis_month) eom, group_concat(distinct fiscal_quarter_number) q, group_concat(distinct fiscal_month_name) name
from times group by 1,2 order by 1,2;
-- name: fiscal_years
select fiscal_year, min(time_id), max(time_id), count(*), group_concat(distinct days_in_fis_year), group_concat(distinct end_of_fis_year) from times group by 1;
-- name: fiscal_quarters
select fiscal_quarter_desc, min(time_id), max(time_id), count(*), group_concat(distinct days_in_fis_quarter), group_concat(distinct end_of_fis_quarter) from times group by 1 order by 1;
-- name: week_numbers
select time_id, day_name, day_number_in_week, calendar_week_number, fiscal_week_number, week_ending_day from times where time_id between '2019-12-26' and '2020-01-08' or time_id between '2019-01-01' and '2019-01-08' or time_id between '2022-12-28' and '2023-01-03' order by time_id;
-- name: text_columns_typeof
select typeof(calendar_quarter_desc), typeof(calendar_month_desc), typeof(week_ending_day), typeof(end_of_fis_year), count(*) from times group by 1,2,3,4;
-- name: days_in_cal_quarter_mismatch
select calendar_quarter_desc, days_in_cal_quarter, count(*) n_rows, min(time_id), max(time_id) from times group by 1,2 order by 1;
-- name: week_ending_id_fd_candidates
select 'id -> (cal_year, cal_week)' fd, count(*), sum(n>1) from (select count(distinct calendar_year||'/'||calendar_week_number) n from times group by week_ending_day_id)
union all select '(cal_year, cal_week) -> id', count(*), sum(n>1) from (select count(distinct week_ending_day_id) n from times group by calendar_year, calendar_week_number)
union all select '(fis_year, fis_week) -> id', count(*), sum(n>1) from (select count(distinct week_ending_day_id) n from times group by fiscal_year, fiscal_week_number)
union all select 'id group sizes 7', count(*), sum(n<>7) from (select count(*) n from times group by week_ending_day_id);
-- name: week_ending_id_runs
select time_id, day_name, week_ending_day, week_ending_day_id, calendar_week_number from times where time_id between '2019-01-01' and '2019-01-16' order by time_id;
