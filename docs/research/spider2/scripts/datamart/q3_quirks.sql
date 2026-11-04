-- name: create_grid
create temp table grid as
select w.week_date, r.region, p.platform, sc.seg, sc.customer_type
from (select distinct week_date from cleaned_weekly_sales) w,
     (select distinct region from cleaned_weekly_sales) r,
     (select distinct platform from cleaned_weekly_sales) p,
     (select distinct segment seg, customer_type from cleaned_weekly_sales) sc;
-- name: grid_vs_rows
select (select count(*) from grid) grid_cells, (select count(*) from cleaned_weekly_sales) rows_present;
-- name: missing_cells
select g.* from grid g left join cleaned_weekly_sales c
  on c.week_date = g.week_date and c.region = g.region and c.platform = g.platform and c.segment = g.seg and c.customer_type = g.customer_type
where c.week_date is null order by 1, 2, 3, 4;
-- name: zero_and_small
select sum(sales = 0) sales_zero, sum(transactions = 0) tx_zero, sum(sales < transactions) sales_lt_tx, min(transactions), max(transactions), min(sales), max(sales) from weekly_sales;
-- name: low_sales_rows
select week_date, region, platform, segment, customer_type, transactions, sales from weekly_sales where sales < transactions or sales < 100 order by sales limit 20;
-- name: sales_multiple_of_tx_patterns
-- generator fingerprint check: transactions in multiples of 40 on small Shopify cells?
select platform, sum(transactions % 10 = 0) tx_mult10, count(*) n from weekly_sales group by 1;
-- name: tx_mod40_by_platform_small
select platform, sum(transactions < 1000) small, sum(transactions < 1000 and transactions % 40 = 0) small_mult40 from weekly_sales group by 1;
-- name: avg_tx_by_platform
select platform, round(avg(avg_transaction), 2) mean_avg_tx, min(avg_transaction), max(avg_transaction), round(1.0*sum(sales)/sum(transactions),2) pooled from cleaned_weekly_sales group by 1;
-- name: sales_per_year
select calendar_year, sum(sales) sales, sum(transactions) tx from cleaned_weekly_sales group by 1;
-- name: weekly_totals
select week_date, sum(sales) sales, sum(transactions) tx, count(*) n from cleaned_weekly_sales group by 1 order by 1;
-- name: platform_share
select platform, sum(sales) sales, round(100.0*sum(sales)/(select sum(sales) from weekly_sales),2) pct_sales, sum(transactions) tx from weekly_sales group by 1;
-- name: region_share
select region, sum(sales) sales, round(100.0*sum(sales)/(select sum(sales) from weekly_sales),2) pct from weekly_sales group by 1 order by 2 desc;
-- name: ctype_share
select customer_type, sum(sales) sales, round(100.0*sum(sales)/(select sum(sales) from weekly_sales),2) pct from weekly_sales group by 1;
-- name: segment_share
select coalesce(segment,'<NULL>') seg, sum(sales) sales, round(100.0*sum(sales)/(select sum(sales) from weekly_sales),2) pct from weekly_sales group by 1;
-- name: cell_sales_quantiles
with s as (select sales, row_number() over (order by sales) rn, count(*) over () n from weekly_sales)
select max(case when rn = cast(n*0.05 as int) then sales end) p5, max(case when rn = cast(n*0.25 as int) then sales end) p25,
       max(case when rn = cast(n*0.5 as int) then sales end) p50, max(case when rn = cast(n*0.75 as int) then sales end) p75,
       max(case when rn = cast(n*0.95 as int) then sales end) p95, max(sales) mx from s;
-- name: week_to_week_cell_change
-- log ratio of a cell's sales to the same cell the previous week
with x as (select region, platform, segment, customer_type, week_date, sales,
  lag(sales) over (partition by region, platform, segment, customer_type order by week_date) prev,
  julianday(week_date) - julianday(lag(week_date) over (partition by region, platform, segment, customer_type order by week_date)) gap
  from cleaned_weekly_sales)
select count(*) pairs, round(avg(1.0*sales/prev), 4) mean_ratio, sum(1.0*sales/prev between 0.9 and 1.1) within_10pct, sum(1.0*sales/prev > 2) more_than_double
from x where gap = 7 and prev > 0;
