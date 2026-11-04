-- name: row_counts
select 'veg_txn_df' t, count(*) n from veg_txn_df union all select 'veg_whsle_df', count(*) from veg_whsle_df
union all select 'veg_cat', count(*) from veg_cat union all select 'veg_loss_rate_df', count(*) from veg_loss_rate_df;
-- name: typeof_txn
select typeof("index") i, typeof(txn_date) d, typeof(txn_time) t, typeof(item_code) c, typeof("qty_sold(kg)") q, typeof("unit_selling_px_rmb/kg") p,
       typeof("sale/return") sr, typeof("discount(%)") dc, typeof(day_of_week) dw, count(*) n from veg_txn_df group by 1,2,3,4,5,6,7,8,9;
-- name: typeof_whsle
select typeof("index"), typeof(whsle_date), typeof(item_code), typeof("whsle_px_rmb-kg"), count(*) from veg_whsle_df group by 1,2,3,4;
-- name: typeof_cat_loss
select 'cat' t, typeof("index"), typeof(item_code), typeof(item_name), typeof(category_code), typeof(category_name), count(*) from veg_cat group by 2,3,4,5,6
union all select 'loss', typeof("index"), typeof(item_code), typeof(item_name), typeof("loss_rate_%"), '', count(*) from veg_loss_rate_df group by 2,3,4,5;
-- name: index_columns
select 'txn' t, min("index"), max("index"), count(*), count(distinct "index"), sum("index" = rowid - 1) idx_eq_rowid_minus_1 from veg_txn_df
union all select 'whsle', min("index"), max("index"), count(*), count(distinct "index"), sum("index" = rowid - 1) from veg_whsle_df
union all select 'cat', min("index"), max("index"), count(*), count(distinct "index"), sum("index" = rowid - 1) from veg_cat
union all select 'loss', min("index"), max("index"), count(*), count(distinct "index"), sum("index" = rowid - 1) from veg_loss_rate_df;
-- name: date_formats
select 'txn' t, length(txn_date) l, substr(txn_date, 11) suffix, count(*), min(txn_date), max(txn_date) from veg_txn_df group by 2, 3
union all select 'whsle', length(whsle_date), substr(whsle_date, 11), count(*), min(whsle_date), max(whsle_date) from veg_whsle_df group by 2, 3;
-- name: time_formats
select length(txn_time) l, count(*), min(txn_time), max(txn_time), sum(txn_time glob '[0-2][0-9]:[0-5][0-9]:[0-5][0-9]') hhmmss from veg_txn_df group by 1;
-- name: subsecond_times
select count(*) from veg_txn_df where txn_time like '%.%';
-- name: key_cat
select count(*) n, count(distinct item_code) items, count(distinct item_name) names, count(distinct category_code) cats, count(distinct category_name) cat_names from veg_cat;
-- name: key_loss
select count(*) n, count(distinct item_code) items, count(distinct item_name) names from veg_loss_rate_df;
-- name: categories
select category_code, category_name, count(*) items from veg_cat group by 1, 2 order by 1;
-- name: loss_vs_cat_items
select (select count(*) from veg_loss_rate_df l where not exists (select 1 from veg_cat c where c.item_code = l.item_code)) loss_not_in_cat,
       (select count(*) from veg_cat c where not exists (select 1 from veg_loss_rate_df l where c.item_code = l.item_code)) cat_not_in_loss,
       (select count(*) from veg_cat c join veg_loss_rate_df l on l.item_code = c.item_code where l.item_name = c.item_name) same_name,
       (select count(*) from veg_cat c join veg_loss_rate_df l on l.item_code = c.item_code where l.item_name <> c.item_name) diff_name;
-- name: loss_name_differences
select c.item_code, c.item_name cat_name, l.item_name loss_name from veg_cat c join veg_loss_rate_df l on l.item_code = c.item_code where l.item_name <> c.item_name;
-- name: duplicate_item_names_cat
select item_name, count(*), group_concat(item_code) from veg_cat group by 1 having count(*) > 1;
-- name: row_order_cat_vs_loss
select sum(c.item_code = l.item_code) same_position, count(*) n from veg_cat c join veg_loss_rate_df l on l."index" = c."index";
-- name: cat_sorted_by
select count(*) pairs, sum(category_code > lc or (category_code = lc and item_code > li)) sorted_cat_item, sum(item_code > li) sorted_item
from (select category_code, item_code, lag(category_code) over (order by rowid) lc, lag(item_code) over (order by rowid) li from veg_cat) where lc is not null;
-- name: loss_sorted_by
select count(*) pairs, sum(item_code > li) sorted_item from (select item_code, lag(item_code) over (order by rowid) li from veg_loss_rate_df) where li is not null;
-- name: orphans
select (select count(*) from veg_txn_df t where not exists (select 1 from veg_cat c where c.item_code = t.item_code)) txn_orphans,
       (select count(distinct item_code) from veg_txn_df) txn_items,
       (select count(*) from veg_whsle_df w where not exists (select 1 from veg_cat c where c.item_code = w.item_code)) whsle_orphans,
       (select count(distinct item_code) from veg_whsle_df) whsle_items,
       (select count(*) from veg_cat c where not exists (select 1 from veg_txn_df t where t.item_code = c.item_code)) cat_never_sold,
       (select count(*) from veg_cat c where not exists (select 1 from veg_whsle_df w where w.item_code = c.item_code)) cat_never_priced;
-- name: whsle_key
select count(*) n, count(distinct whsle_date || '|' || item_code) d from veg_whsle_df;
-- name: txn_dup_full_rows
select count(*) n, count(distinct txn_date || '|' || txn_time || '|' || item_code || '|' || "qty_sold(kg)" || '|' || "unit_selling_px_rmb/kg" || '|' || "sale/return" || '|' || "discount(%)") d from veg_txn_df;
-- name: txn_rowid_order
select count(*) pairs, sum(k >= lk) nondecreasing, sum(k < lk) backwards from (select txn_date || txn_time k, lag(txn_date || txn_time) over (order by rowid) lk from veg_txn_df) where lk is not null;
-- name: whsle_rowid_order
select count(*) pairs, sum(whsle_date > ld or (whsle_date = ld and item_code > li)) sorted_date_item, sum(whsle_date >= ld) date_nondecreasing
from (select whsle_date, item_code, lag(whsle_date) over (order by rowid) ld, lag(item_code) over (order by rowid) li from veg_whsle_df) where ld is not null;
-- name: day_of_week_check
select count(*) n, sum(day_of_week = case strftime('%w', txn_date) when '0' then 'Sunday' when '1' then 'Monday' when '2' then 'Tuesday' when '3' then 'Wednesday'
  when '4' then 'Thursday' when '5' then 'Friday' else 'Saturday' end) dow_ok from veg_txn_df;
-- name: sale_return_values
select "sale/return", count(*), min("qty_sold(kg)"), max("qty_sold(kg)") from veg_txn_df group by 1;
-- name: discount_values
select "discount(%)", count(*) from veg_txn_df group by 1;
-- name: null_counts
select sum(txn_date is null) + sum(txn_time is null) + sum(item_code is null) + sum("qty_sold(kg)" is null) + sum("unit_selling_px_rmb/kg" is null)
       + sum("sale/return" is null) + sum("discount(%)" is null) + sum(day_of_week is null) txn_nulls,
       (select sum(whsle_date is null) + sum(item_code is null) + sum("whsle_px_rmb-kg" is null) from veg_whsle_df) whsle_nulls from veg_txn_df;
