-- name: quantity_values
select quantity_sold, count(*) from sales group by 1;
-- name: amount_grid
-- amounts on the cent grid? (text form and value*100 integrality)
select sum(abs(amount_sold*100 - round(amount_sold*100)) > 1e-6) off_cent, min(amount_sold), max(amount_sold), count(distinct amount_sold) from sales;
-- name: costs_grid
select sum(abs(unit_cost*100 - round(unit_cost*100)) > 1e-6) cost_off_cent, sum(abs(unit_price*100 - round(unit_price*100)) > 1e-6) price_off_cent,
 min(unit_cost), max(unit_cost), min(unit_price), max(unit_price), sum(unit_cost > unit_price) cost_gt_price from costs;
-- name: distinct_sales_keys_4
-- the costs grain (prod,time,channel,promo) seen from sales
select count(*) from (select 1 from sales group by prod_id, time_id, channel_id, promo_id);
-- name: amount_fd_on_costs_key
-- is amount_sold a function of (prod,time,channel,promo)?
select sum(n=1) single_amount, sum(n>1) multi_amount, count(*) from (select count(distinct amount_sold) n from sales group by prod_id, time_id, channel_id, promo_id);
-- name: amount_fd_on_prod_time
select sum(n=1) single_amount, sum(n>1) multi_amount, count(*) from (select count(distinct amount_sold) n from sales group by prod_id, time_id);
-- name: amount_vs_unit_price
select count(*) n, sum(abs(s.amount_sold - c.unit_price) < 0.005) eq_price, sum(s.amount_sold > c.unit_price + 0.005) above, sum(s.amount_sold < c.unit_price - 0.005) below,
 avg(s.amount_sold / c.unit_price) mean_ratio, min(s.amount_sold / c.unit_price), max(s.amount_sold / c.unit_price)
from sales s join costs c on c.prod_id=s.prod_id and c.time_id=s.time_id and c.channel_id=s.channel_id and c.promo_id=s.promo_id;
-- name: amount_vs_list_price
select count(*), sum(abs(s.amount_sold - p.prod_list_price) < 0.005) eq_list, avg(s.amount_sold / p.prod_list_price), min(s.amount_sold / p.prod_list_price), max(s.amount_sold / p.prod_list_price) from sales s join products p using(prod_id);
-- name: unmatched_sales_by_channel_promo
select s.channel_id, s.promo_id, count(*), sum(not exists(select 1 from costs c where c.prod_id=s.prod_id and c.time_id=s.time_id and c.channel_id=s.channel_id and c.promo_id=s.promo_id)) no_cost
from sales s group by 1,2;
-- name: unmatched_sales_detail
select s.prod_id, s.time_id, s.channel_id, s.promo_id, count(*) from sales s
where not exists(select 1 from costs c where c.prod_id=s.prod_id and c.time_id=s.time_id and c.channel_id=s.channel_id and c.promo_id=s.promo_id) and s.channel_id<>9
group by 1,2,3,4 order by 5 desc limit 15;
-- name: unmatched_sales_non9_summary
select count(*) rows_, count(distinct prod_id||'/'||time_id||'/'||channel_id||'/'||promo_id) keys_, min(time_id), max(time_id), count(distinct prod_id) prods from sales s
where not exists(select 1 from costs c where c.prod_id=s.prod_id and c.time_id=s.time_id and c.channel_id=s.channel_id and c.promo_id=s.promo_id) and s.channel_id<>9;
-- name: costs_unit_price_fd_prod_time
-- is unit_price/unit_cost constant per (prod, time) across channel/promo?
select sum(np=1), sum(np>1), sum(nc=1), sum(nc>1), count(*) from (select count(distinct unit_price) np, count(distinct unit_cost) nc from costs group by prod_id, time_id);
-- name: costs_cost_const_per_prod_month
select sum(nc=1) const_cost, sum(nc>1) varies, count(*) from (select count(distinct unit_cost) nc from costs group by prod_id, substr(time_id,1,7));
-- name: costs_cost_const_per_prod_quarter
select sum(nc=1) const_cost, sum(nc>1) varies, count(*) from (select count(distinct c.unit_cost) nc from costs c join times t using(time_id) group by c.prod_id, t.calendar_quarter_desc);
-- name: costs_price_const_per_prod_quarter
select sum(nc=1), sum(nc>1), count(*) from (select count(distinct c.unit_price) nc from costs c join times t using(time_id) group by c.prod_id, t.calendar_quarter_desc);
-- name: costs_example
select * from costs where prod_id=14 and time_id between '2019-01-01' and '2019-03-31' order by time_id, channel_id limit 30;
-- name: sales_example_same_key4
select prod_id, time_id, channel_id, promo_id, amount_sold, count(*) from sales where prod_id=14 and time_id between '2019-01-01' and '2019-01-31' group by 1,2,3,4,5 order by 2,3;
-- name: rowid_order
select sum(b.prod_id > a.prod_id) prod_up, sum(b.prod_id = a.prod_id) prod_eq, sum(b.prod_id < a.prod_id) prod_down,
 sum(b.prod_id = a.prod_id and b.time_id > a.time_id) t_up, sum(b.prod_id = a.prod_id and b.time_id = a.time_id) t_eq, sum(b.prod_id = a.prod_id and b.time_id < a.time_id) t_down, count(*)
from sales a join sales b on b.rowid = a.rowid + 1;
-- name: rowid_order_within_prod_time
select sum(b.channel_id > a.channel_id) ch_up, sum(b.channel_id = a.channel_id) ch_eq, sum(b.channel_id < a.channel_id) ch_down,
 sum(b.channel_id = a.channel_id and b.promo_id = a.promo_id and b.cust_id > a.cust_id) cust_up, sum(b.channel_id = a.channel_id and b.promo_id = a.promo_id and b.cust_id < a.cust_id) cust_down
from sales a join sales b on b.rowid = a.rowid + 1 and b.prod_id=a.prod_id and b.time_id=a.time_id;
-- name: prod_runs
select count(*) runs from (select prod_id, rowid from sales a where not exists (select 1 from sales b where b.rowid = a.rowid-1 and b.prod_id=a.prod_id));
-- name: days_without_sales
select substr(t.time_id,1,4) y, count(*) from times t where not exists (select 1 from sales s where s.time_id=t.time_id) group by 1;
-- name: days_without_sales_list
select t.time_id, t.day_name from times t where not exists (select 1 from sales s where s.time_id=t.time_id) and t.time_id < '2023-01-01';
-- name: cust_day_lines
-- per (cust, day): number of lines and distinct channels
select n, count(*) from (select count(*) n from sales group by cust_id, time_id) group by n order by n limit 20;
-- name: cust_day_channels
select nc, count(*) from (select count(distinct channel_id) nc from sales group by cust_id, time_id) group by nc;
-- name: cust_prod_day_multi_channel
select count(*) from (select 1 from sales group by cust_id, prod_id, time_id having count(*) > 1);
