-- Entity creation rules: when is each item first seen?
-- name: last_event
select max(txn_date || ' ' || txn_time) last_txn, (select max(whsle_date) from veg_whsle_df) last_quote from veg_txn_df where txn_date = '2023-06-30 00:00:00';
-- name: first_quote_vs_first_sale
with q as (select item_code, min(whsle_date) fq from veg_whsle_df group by 1), s as (select item_code, min(txn_date) fs from veg_txn_df group by 1)
select count(*) items, sum(s.fs is null) never_sold, sum(fq < fs) quoted_before_first_sale, sum(fq = fs) quoted_same_day, sum(fq > fs) quoted_after,
       sum(fq = '2020-07-01 00:00:00') first_quote_on_day1 from q left join s using (item_code);
-- name: first_quote_by_year
select substr(min_q, 1, 4) y, count(*) items from (select item_code, min(whsle_date) min_q from veg_whsle_df group by 1) group by 1;
-- name: items_per_category_sold
select c.category_name, count(distinct t.item_code) items_sold from veg_txn_df t join veg_cat c using (item_code) group by 1;
-- name: item_code_prefixes
select substr(item_code, 1, 7) prefix, count(*) from veg_cat group by 1;
