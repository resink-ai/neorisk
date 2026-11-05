-- Derived columns and value grids.
-- name: sale_return_is_sign
select count(*) n, sum(("sale/return" = 'return') = ("qty_sold(kg)" < 0)) sign_rule_ok, sum("qty_sold(kg)" = 0) zero_qty from veg_txn_df;
-- name: qty_grid
select count(*) n, sum(abs("qty_sold(kg)" * 1000 - round("qty_sold(kg)" * 1000)) < 1e-6) grams, sum("qty_sold(kg)" = round("qty_sold(kg)" * 1000) / 1000.0) exact_from_grams,
       sum("qty_sold(kg)" = cast("qty_sold(kg)" as integer)) whole_kg from veg_txn_df;
-- name: qty_decimals
select case when "qty_sold(kg)" = round("qty_sold(kg)", 0) then 0 when "qty_sold(kg)" = round("qty_sold(kg)", 1) then 1 when "qty_sold(kg)" = round("qty_sold(kg)", 2) then 2
            when "qty_sold(kg)" = round("qty_sold(kg)", 3) then 3 else 9 end dp, count(*) from veg_txn_df group by 1;
-- name: price_grid
select count(*) n, sum("unit_selling_px_rmb/kg" = round("unit_selling_px_rmb/kg" * 100) / 100.0) exact_from_fen,
       sum("unit_selling_px_rmb/kg" = round("unit_selling_px_rmb/kg" * 10) / 10.0) exact_from_jiao, min("unit_selling_px_rmb/kg"), max("unit_selling_px_rmb/kg") from veg_txn_df;
-- name: whsle_grid
select count(*) n, sum("whsle_px_rmb-kg" = round("whsle_px_rmb-kg" * 100) / 100.0) exact_from_fen, min("whsle_px_rmb-kg"), max("whsle_px_rmb-kg"),
       sum("whsle_px_rmb-kg" <= 0) non_positive from veg_whsle_df;
-- name: loss_grid
select count(*) n, sum("loss_rate_%" = round("loss_rate_%" * 100) / 100.0) exact_2dp, min("loss_rate_%"), max("loss_rate_%"), sum("loss_rate_%" = 0) zero from veg_loss_rate_df;
-- name: loss_name_is_cat_name
select count(*) n, sum(l.item_name = c.item_name) same from veg_loss_rate_df l join veg_cat c on c.item_code = l.item_code;
-- name: whsle_index_rule
select count(*) n, sum("index" = rn) ok from (select "index", row_number() over (order by whsle_date, item_code) - 1 rn from veg_whsle_df);
-- name: cat_index_rule
select count(*) n, sum("index" = rn) ok from (select "index", row_number() over (order by category_code, item_code) - 1 rn from veg_cat);
-- name: loss_index_rule
select count(*) n, sum("index" = rn) ok from (select "index", row_number() over (order by item_code) - 1 rn from veg_loss_rate_df);
-- name: txn_ties
-- rows sharing (date, time): how many, and is their file order explained by any column?
select count(*) rows_in_ties, count(distinct txn_date || txn_time) tie_groups from (select txn_date, txn_time, count(*) over (partition by txn_date, txn_time) c from veg_txn_df) where c > 1;
-- name: txn_tie_order_candidates
with x as (select "index", txn_date, txn_time, item_code, "qty_sold(kg)" q, "unit_selling_px_rmb/kg" p,
  lag(item_code) over (order by "index") li, lag("qty_sold(kg)") over (order by "index") lq, lag(txn_date || txn_time) over (order by "index") lk from veg_txn_df)
select count(*) tie_pairs, sum(item_code > li) item_increasing, sum(item_code < li) item_decreasing, sum(item_code = li) item_same,
       sum(q > lq) qty_increasing from x where lk = txn_date || txn_time;
-- name: txn_index_from_date_time_only
select count(*) n, sum("index" = rn) ok from (select "index", row_number() over (order by txn_date, txn_time, "index") - 1 rn from veg_txn_df);
-- name: txn_full_duplicates
select count(*) dup_groups, sum(c) rows_in_groups, sum(c - 1) extra_rows, max(c) max_copies from (
  select count(*) c from veg_txn_df group by txn_date, txn_time, item_code, "qty_sold(kg)", "unit_selling_px_rmb/kg", "sale/return" having count(*) > 1);
-- name: txn_dup_examples
select txn_date, txn_time, item_code, "qty_sold(kg)", "unit_selling_px_rmb/kg", count(*) c, group_concat("index") idx from veg_txn_df
group by txn_date, txn_time, item_code, "qty_sold(kg)", "unit_selling_px_rmb/kg", "sale/return" having count(*) > 1 order by c desc limit 5;
-- name: dup_adjacent
-- are duplicate copies adjacent in index order?
with g as (select txn_date, txn_time, item_code, "qty_sold(kg)" q, "unit_selling_px_rmb/kg" p, "sale/return" sr, max("index") - min("index") + 1 span, count(*) c
  from veg_txn_df group by 1,2,3,4,5,6 having count(*) > 1)
select sum(span = c) adjacent, count(*) groups from g;
