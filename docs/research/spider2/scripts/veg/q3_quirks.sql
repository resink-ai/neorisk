-- name: create_daily
create temp table sold_days as select txn_date d, item_code, count(*) n, sum("qty_sold(kg)") kg from veg_txn_df group by 1, 2;
-- name: sales_with_whsle_price
select count(*) item_days_sold, sum(exists (select 1 from veg_whsle_df w where w.whsle_date = s.d and w.item_code = s.item_code)) with_price from sold_days s;
-- name: whsle_without_sales
select count(*) whsle_rows, sum(not exists (select 1 from sold_days s where s.d = w.whsle_date and s.item_code = w.item_code)) no_sale_that_day from veg_whsle_df w;
-- name: days
select count(distinct txn_date) sale_days, (select count(distinct whsle_date) from veg_whsle_df) whsle_days,
       julianday('2023-06-30') - julianday('2020-07-01') + 1 calendar_days from veg_txn_df;
-- name: missing_sale_days
with recursive cal(d) as (select '2020-07-01' union all select date(d, '+1 day') from cal where d < '2023-06-30')
select d from cal where not exists (select 1 from veg_txn_df t where t.txn_date = d || ' 00:00:00') order by d;
-- name: missing_whsle_days
with recursive cal(d) as (select '2020-07-01' union all select date(d, '+1 day') from cal where d < '2023-06-30')
select d from cal where not exists (select 1 from veg_whsle_df t where t.whsle_date = d || ' 00:00:00') order by d;
-- name: rows_per_year
select substr(txn_date, 1, 4) y, count(*) rows_, round(sum("qty_sold(kg)"), 3) kg, round(sum("qty_sold(kg)" * "unit_selling_px_rmb/kg"), 2) revenue from veg_txn_df group by 1;
-- name: rows_per_month
select substr(txn_date, 1, 7) ym, count(*) rows_ from veg_txn_df group by 1 order by 1;
-- name: per_day_quantiles
with d as (select txn_date, count(*) n from veg_txn_df group by 1), s as (select n, row_number() over (order by n) rn, count(*) over () c from d)
select min(n), max(case when rn = cast(c*0.1 as int) then n end) p10, max(case when rn = cast(c*0.5 as int) then n end) p50,
       max(case when rn = cast(c*0.9 as int) then n end) p90, max(n) from s;
-- name: busiest_days
select txn_date, count(*) n from veg_txn_df group by 1 order by 2 desc limit 5;
-- name: hour_of_day
select substr(txn_time, 1, 2) h, count(*) n from veg_txn_df group by 1 order by 1;
-- name: weekday_mix
select day_of_week, count(*) n, count(distinct txn_date) days, round(1.0 * count(*) / count(distinct txn_date), 1) per_day from veg_txn_df group by 1 order by 2 desc;
-- name: gap_seconds_within_day
-- inter-arrival seconds between consecutive transactions on the same day
with x as (select txn_date, (julianday(substr(txn_date,1,10) || ' ' || txn_time) - julianday(lag(substr(txn_date,1,10) || ' ' || txn_time) over (partition by txn_date order by "index"))) * 86400 g from veg_txn_df)
select count(*) n, sum(round(g) = 0) zero, sum(round(g) between 1 and 10) s1_10, sum(round(g) between 11 and 60) s11_60, sum(round(g) between 61 and 300) s61_300, sum(round(g) > 300) over300, round(avg(g), 1) mean from x where g is not null;
-- name: qty_quantiles
with s as (select "qty_sold(kg)" v, row_number() over (order by "qty_sold(kg)") rn, count(*) over () c from veg_txn_df where "sale/return" = 'sale')
select max(case when rn = cast(c*0.05 as int) then v end) p5, max(case when rn = cast(c*0.25 as int) then v end) p25, max(case when rn = cast(c*0.5 as int) then v end) p50,
       max(case when rn = cast(c*0.75 as int) then v end) p75, max(case when rn = cast(c*0.95 as int) then v end) p95, max(case when rn = cast(c*0.999 as int) then v end) p999, max(v) mx from s;
-- name: whole_kg_by_category
-- whole-number quantities = items sold by piece/bag?
select c.category_name, count(*) n, sum(t."qty_sold(kg)" = cast(t."qty_sold(kg)" as integer)) whole, round(100.0 * sum(t."qty_sold(kg)" = cast(t."qty_sold(kg)" as integer)) / count(*), 1) pct
from veg_txn_df t join veg_cat c using (item_code) group by 1 order by 1;
-- name: items_always_whole
select count(*) items, sum(whole = n) always_whole, sum(whole = 0) never_whole from (select item_code, count(*) n, sum("qty_sold(kg)" = cast("qty_sold(kg)" as integer)) whole from veg_txn_df group by 1);
-- name: category_mix
select c.category_name, count(*) n, round(100.0 * count(*) / (select count(*) from veg_txn_df), 2) pct from veg_txn_df t join veg_cat c using (item_code) group by 1 order by 2 desc;
-- name: item_popularity
with p as (select item_code, count(*) n from veg_txn_df group by 1), s as (select n, row_number() over (order by n desc) rn from p)
select max(n) top1, max(case when rn = 10 then n end) top10, max(case when rn = 50 then n end) top50, max(case when rn = 100 then n end) top100, min(n) min_n, count(*) items from s;
-- name: item_active_days
select count(*) items, min(first_day), max(first_day), sum(first_day = '2020-07-01 00:00:00') active_from_start, sum(last_day = '2023-06-30 00:00:00') active_at_end
from (select item_code, min(txn_date) first_day, max(txn_date) last_day from veg_txn_df group by 1);
-- name: items_per_day
with d as (select txn_date, count(distinct item_code) n from veg_txn_df group by 1) select min(n), round(avg(n), 1), max(n) from d;
-- name: markup
-- selling price / wholesale price on the same item-day
select count(*) n, round(avg(t."unit_selling_px_rmb/kg" / w."whsle_px_rmb-kg"), 3) mean_ratio, sum(t."unit_selling_px_rmb/kg" < w."whsle_px_rmb-kg") below_cost
from veg_txn_df t join veg_whsle_df w on w.whsle_date = t.txn_date and w.item_code = t.item_code;
-- name: markup_bands
select case when r < 1 then '<1' when r < 1.2 then '1-1.2' when r < 1.4 then '1.2-1.4' when r < 1.6 then '1.4-1.6' when r < 2 then '1.6-2' else '>=2' end band, count(*) n
from (select t."unit_selling_px_rmb/kg" / w."whsle_px_rmb-kg" r from veg_txn_df t join veg_whsle_df w on w.whsle_date = t.txn_date and w.item_code = t.item_code) group by 1 order by 1;
-- name: price_points_per_item_day
select n_prices, count(*) item_days from (select txn_date, item_code, count(distinct "unit_selling_px_rmb/kg") n_prices from veg_txn_df group by 1, 2) group by 1 order by 1;
-- name: price_ending
select substr(printf('%.2f', "unit_selling_px_rmb/kg"), -1) last_digit, count(*) n from veg_txn_df group by 1 order by 2 desc;
-- name: returns
select count(*) n, round(avg("qty_sold(kg)"), 3) mean_kg, count(distinct item_code) items, min(txn_date), max(txn_date) from veg_txn_df where "sale/return" = 'return';
-- name: loss_rate_dist
select case when "loss_rate_%" = 0 then '0' when "loss_rate_%" < 5 then '0-5' when "loss_rate_%" < 10 then '5-10' when "loss_rate_%" < 15 then '10-15' when "loss_rate_%" < 20 then '15-20' else '>=20' end b, count(*) from veg_loss_rate_df group by 1 order by 1;
-- name: zero_loss_items_sold
select count(*) zero_loss_items, sum(exists (select 1 from veg_txn_df t where t.item_code = l.item_code)) sold from veg_loss_rate_df l where "loss_rate_%" = 0;
-- name: whsle_per_item_quantiles
select min(n), max(n), round(avg(n), 1) from (select item_code, count(*) n from veg_whsle_df group by 1);
-- name: whsle_daily_change
with x as (select item_code, whsle_date, "whsle_px_rmb-kg" p, lag("whsle_px_rmb-kg") over (partition by item_code order by whsle_date) lp,
  julianday(whsle_date) - julianday(lag(whsle_date) over (partition by item_code order by whsle_date)) gap from veg_whsle_df)
select count(*) consecutive_pairs, sum(p = lp) unchanged, round(avg(p / lp), 4) mean_ratio, sum(p / lp > 2 or p / lp < 0.5) jumps_2x from x where gap = 1;
-- name: whsle_extremes
select item_code, whsle_date, "whsle_px_rmb-kg" from veg_whsle_df where "whsle_px_rmb-kg" <= 0.05 or "whsle_px_rmb-kg" >= 100 order by 3 limit 20;
-- name: never_sold_items
select c.item_code, c.item_name, c.category_name, (select count(*) from veg_whsle_df w where w.item_code = c.item_code) whsle_rows
from veg_cat c where not exists (select 1 from veg_txn_df t where t.item_code = c.item_code);
