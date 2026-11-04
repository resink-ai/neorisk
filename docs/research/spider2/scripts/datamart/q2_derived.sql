-- Is cleaned_weekly_sales an exact function of weekly_sales?  The candidate rule is the
-- 8 Week SQL Challenge #5 "data cleansing" step.  Rows align by rowid (q1:rowid_vs_cleaned_rowid).
-- name: create_rebuilt
create temp table parts as
select rowid rid, *,
  cast(substr(week_date, 1, instr(week_date, '/') - 1) as integer) d,
  substr(week_date, instr(week_date, '/') + 1) rest
from weekly_sales;
-- name: create_rebuilt2
create temp table parts2 as
select *, cast(substr(rest, 1, instr(rest, '/') - 1) as integer) m,
       2000 + cast(substr(rest, instr(rest, '/') + 1) as integer) y from parts;
-- name: create_rebuilt3
create temp table rebuilt as
select rid,
  y || '-' || m || '-' || d as week_date_formatted,
  printf('%04d-%02d-%02d', y, m, d) as week_date,
  region, platform,
  coalesce(segment, 'unknown') as segment,
  customer_type, transactions, sales,
  cast(strftime('%W', printf('%04d-%02d-%02d', y, m, d)) as integer) as week_number_W,
  (cast(strftime('%j', date(printf('%04d-%02d-%02d', y, m, d), '-3 days', 'weekday 4')) as integer) - 1) / 7 + 1 as week_number_V,
  (cast(strftime('%j', printf('%04d-%02d-%02d', y, m, d)) as integer) - 1) / 7 + 1 as week_number_doy,
  m as month_number, y as calendar_year,
  case substr(segment, 2, 1) when '1' then 'Young Adults' when '2' then 'Middle Aged'
       when '3' then 'Retirees' when '4' then 'Retirees' else 'unknown' end as age_band,
  case substr(segment, 1, 1) when 'C' then 'Couples' when 'F' then 'Families' else 'unknown' end as demographic,
  round(1.0 * sales / transactions, 2) as avg_transaction_float,
  -- exact decimal round-half-up of sales/transactions to cents, then cents/100
  ((200 * sales + transactions) / (2 * transactions)) / 100.0 as avg_transaction
from parts2;
-- name: week_number_candidates
select sum(c.week_number = r.week_number_W) by_W, sum(c.week_number = r.week_number_V) by_V_iso_via_thursday,
       sum(c.week_number = r.week_number_doy) by_dayofyear, count(*) n
from cleaned_weekly_sales c join rebuilt r on r.rid = c.rowid;
-- name: per_column_matches
select count(*) n,
  sum(c.week_date_formatted = r.week_date_formatted) wdf, sum(c.week_date = r.week_date) wd,
  sum(c.region = r.region) region, sum(c.platform = r.platform) platform, sum(c.segment = r.segment) segment,
  sum(c.customer_type = r.customer_type) ctype, sum(c.transactions = r.transactions) tx, sum(c.sales = r.sales) sales,
  sum(c.month_number = r.month_number) mn, sum(c.calendar_year = r.calendar_year) cy,
  sum(c.age_band = r.age_band) ab, sum(c.demographic = r.demographic) dm,
  sum(c.avg_transaction = r.avg_transaction_float) avg_tx_sqlite_round, sum(c.avg_transaction = r.avg_transaction) avg_tx_half_up_cents,
  sum(c.week_number = r.week_number_V) week_number_iso
from cleaned_weekly_sales c join rebuilt r on r.rid = c.rowid;
-- name: avg_tx_mismatches
select c.rowid, c.transactions, c.sales, c.avg_transaction, r.avg_transaction_float sqlite_round, r.avg_transaction half_up, printf('%.17g', 1.0*c.sales/c.transactions) raw
from cleaned_weekly_sales c join rebuilt r on r.rid = c.rowid where c.avg_transaction <> r.avg_transaction_float limit 20;
-- name: multiset_diff_cleaned_minus_rebuilt
select count(*) n from (
  select week_date_formatted, week_date, region, platform, segment, customer_type, transactions, sales, week_number, month_number, calendar_year, age_band, demographic, avg_transaction from cleaned_weekly_sales
  except
  select week_date_formatted, week_date, region, platform, segment, customer_type, transactions, sales, week_number_V, month_number, calendar_year, age_band, demographic, avg_transaction from rebuilt);
-- name: multiset_diff_rebuilt_minus_cleaned
select count(*) n from (
  select week_date_formatted, week_date, region, platform, segment, customer_type, transactions, sales, week_number_V, month_number, calendar_year, age_band, demographic, avg_transaction from rebuilt
  except
  select week_date_formatted, week_date, region, platform, segment, customer_type, transactions, sales, week_number, month_number, calendar_year, age_band, demographic, avg_transaction from cleaned_weekly_sales);
-- name: week_number_vs_dates
select week_date, week_number, cast(strftime('%W', week_date) as integer) W, (cast(strftime('%j', date(week_date, '-3 days', 'weekday 4')) as integer) - 1) / 7 + 1 iso, strftime('%w', week_date) dow
from cleaned_weekly_sales group by week_date having week_number <> W or week_date in ('2018-03-26','2020-08-31') order by week_date limit 10;
-- name: weekday_of_week_date
select strftime('%w', week_date) dow_0_sunday, count(distinct week_date) weeks from cleaned_weekly_sales group by 1;
-- name: week_gaps
select gap, count(*) n from (select julianday(week_date) - julianday(lag(week_date) over (order by week_date)) gap
from (select distinct week_date from cleaned_weekly_sales)) group by 1;
-- name: weeks_per_year
select calendar_year, count(distinct week_date) weeks, min(week_date), max(week_date), min(week_number), max(week_number) from cleaned_weekly_sales group by 1;
-- name: avg_transaction_text
select count(*) n, sum(avg_transaction = round(avg_transaction, 2)) two_dp, min(avg_transaction), max(avg_transaction) from cleaned_weekly_sales;
-- name: avg_transaction_half_up_ties
-- how many rows are exact .xx5 ties (where float round and half-up can differ)
select sum((sales * 1000) % transactions = 0 and ((sales * 1000) / transactions) % 10 = 5) exact_ties, count(*) n from weekly_sales;
