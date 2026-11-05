-- name: row_counts
select 'weekly_sales' t, count(*) n from weekly_sales union all select 'cleaned_weekly_sales', count(*) from cleaned_weekly_sales;
-- name: typeof_weekly_sales
select typeof(week_date) wd, typeof(region) r, typeof(platform) p, typeof(segment) s, typeof(customer_type) c, typeof(transactions) tx, typeof(sales) sa, count(*) n
from weekly_sales group by 1,2,3,4,5,6,7;
-- name: typeof_cleaned
select typeof(week_date_formatted) wdf, typeof(week_date) wd, typeof(segment) s, typeof(week_number) wn, typeof(month_number) mn, typeof(calendar_year) cy,
       typeof(age_band) ab, typeof(demographic) dm, typeof(avg_transaction) at, count(*) n
from cleaned_weekly_sales group by 1,2,3,4,5,6,7,8,9;
-- name: null_empty_counts
select sum(segment is null) seg_null, sum(segment='') seg_empty, sum(segment='null') seg_text_null, sum(region is null) reg_null,
       sum(platform is null) plat_null, sum(customer_type is null) ct_null, sum(transactions is null) tx_null, sum(sales is null) sales_null
from weekly_sales;
-- name: key_uniqueness
select count(*) n, count(distinct week_date||'|'||region||'|'||platform||'|'||coalesce(segment,'<NULL>')||'|'||customer_type) d from weekly_sales;
-- name: key_uniqueness_cleaned
select count(*) n, count(distinct week_date||'|'||region||'|'||platform||'|'||segment||'|'||customer_type) d from cleaned_weekly_sales;
-- name: dimension_values
select 'region' dim, region v, count(*) n from weekly_sales group by 2
union all select 'platform', platform, count(*) from weekly_sales group by 2
union all select 'segment', coalesce(segment,'<NULL>'), count(*) from weekly_sales group by 2
union all select 'customer_type', customer_type, count(*) from weekly_sales group by 2;
-- name: segment_by_customer_type
select customer_type, coalesce(segment,'<NULL>') seg, count(*) n from weekly_sales group by 1,2 order by 1,2;
-- name: week_date_formats
select length(week_date) len, count(*) n, min(week_date), max(week_date) from weekly_sales group by 1;
-- name: weeks
select count(distinct week_date) weeks from weekly_sales;
-- name: grid_size
-- full cross product of dims actually used vs rows present
select (select count(distinct week_date) from weekly_sales) * (select count(distinct region) from weekly_sales) * (select count(distinct platform) from weekly_sales) * 22 as full_grid_if_22_combos,
       (select count(*) from (select distinct coalesce(segment,'<NULL>'), customer_type from weekly_sales)) seg_ct_combos;
-- name: rows_per_week
select n, count(*) weeks from (select week_date, count(*) n from weekly_sales group by 1) group by 1 order by 1;
-- name: rowid_order_sample
select rowid, week_date, region, platform, segment, customer_type from weekly_sales where rowid in (1,2,3,4,5,236,237,238,239,17116,17117);
-- name: rowid_vs_cleaned_rowid
-- does cleaned keep the source row order (same rowid -> same key)?
select count(*) n, sum(w.region=c.region and w.platform=c.platform and coalesce(w.segment,'unknown')=c.segment and w.customer_type=c.customer_type
       and w.transactions=c.transactions and w.sales=c.sales) same_row_except_date
from weekly_sales w join cleaned_weekly_sales c on c.rowid=w.rowid;
