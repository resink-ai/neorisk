-- name: local301_gold_sql
-- Spider2 gold SQL (gold/local301.sql) condensed: same expressions, one block per year.
select y as year, before_effect, after_effect, after_effect - before_effect change_amount,
       round(((after_effect * 1.0 / before_effect) - 1) * 100, 2) percent_change,
       ((after_effect * 1.0 / before_effect) - 1) * 100 percent_change_raw
from (select y,
        sum(case when delta_weeks between 1 and 4 then sales end) after_effect,
        sum(case when delta_weeks between -3 and 0 then sales end) before_effect
      from (select y, sales, round((julianday(week_date) - julianday(y || '-06-15')) / 7.0) + 1 delta_weeks
            from cleaned_weekly_sales, (select '2018' y union all select '2019' union all select '2020')
            where calendar_year = cast(y as integer) or 1 = 1)
      group by y)
order by year;
-- name: local301_by_date_windows
-- plain reading: 4 week_dates before June 15 and 4 on/after it
select calendar_year, sum(case when week_date <  printf('%d-06-15', calendar_year) and week_date >= date(printf('%d-06-15', calendar_year), '-28 days') then sales end) pre,
       sum(case when week_date >= printf('%d-06-15', calendar_year) and week_date <  date(printf('%d-06-15', calendar_year), '+28 days') then sales end) post
from cleaned_weekly_sales group by 1;
-- name: local301_weeks_in_windows
select y, delta_weeks, min(week_date), max(week_date), count(distinct week_date) weeks from (
  select y, week_date, round((julianday(week_date) - julianday(y || '-06-15')) / 7.0) + 1 delta_weeks
  from cleaned_weekly_sales, (select '2018' y union all select '2019' union all select '2020'))
where delta_weeks between -3 and 4 group by 1, 2 order by 1, 2;
-- name: local302_attr_values
-- 12 weeks before 2020-06-15 vs 12 weeks from it, per attribute value; % rounded to 2 dp
create temp table l302 as
with base as (select *, case when week_date >= '2020-06-15' and week_date < date('2020-06-15', '+84 days') then 'after'
                             when week_date <  '2020-06-15' and week_date >= date('2020-06-15', '-84 days') then 'before' end w
              from cleaned_weekly_sales where calendar_year = 2020),
u as (select 'region' attr, region v, w, sales from base union all select 'platform', platform, w, sales from base
      union all select 'age_band', age_band, w, sales from base union all select 'demographic', demographic, w, sales from base
      union all select 'customer_type', customer_type, w, sales from base)
select attr, v, sum(case when w = 'before' then sales end) before_s, sum(case when w = 'after' then sales end) after_s,
       round(100.0 * (sum(case when w = 'after' then sales end) - sum(case when w = 'before' then sales end)) / sum(case when w = 'before' then sales end), 2) pct,
       100.0 * (sum(case when w = 'after' then sales end) - sum(case when w = 'before' then sales end)) / sum(case when w = 'before' then sales end) pct_raw
from u group by 1, 2;
-- name: local302_by_attr
select attr, avg(pct) avg_of_2dp_pcts, avg(round(pct_raw, 3)) avg_of_3dp_pcts, avg(pct_raw) avg_of_raw_pcts, count(*) n_values from l302 group by 1 order by 2;
-- name: local302_values
select * from l302 order by attr, v;
