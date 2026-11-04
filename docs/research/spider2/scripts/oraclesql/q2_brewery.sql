-- name: date_ranges
select 'purchases.purchased' c, min(purchased), max(purchased), count(*) from purchases
union all select 'monthly_sales.mth', min(mth), max(mth), count(*) from monthly_sales
union all select 'monthly_budget.mth', min(mth), max(mth), count(*) from monthly_budget
union all select 'orders.ordered', min(ordered), max(ordered), count(*) from orders
union all select 'picking_list.created', min(created), max(created), count(*) from picking_list
union all select 'picking_log.log_time', min(log_time), max(log_time), count(*) from picking_log
union all select 'emp_hire_periods.start_', min(start_), max(start_), count(*) from emp_hire_periods
union all select 'emp_hire_periods.end_', min(end_), max(end_), count(end_) from emp_hire_periods
union all select 'ticker.day', min(day), max(day), count(*) from ticker
union all select 'web_counter_hist.day', min(day), max(day), count(*) from web_counter_hist
union all select 'web_page_visits.visit_time', min(visit_time), max(visit_time), count(*) from web_page_visits
union all select 'server_heartbeat.beat_time', min(beat_time), max(beat_time), count(*) from server_heartbeat
union all select 'web_devices.day', min(day), max(day), count(*) from web_devices
union all select 'web_demographics.day', min(day), max(day), count(*) from web_demographics;
-- name: dates_valid
select 'purchases' t, count(*) n, sum(date(purchased) = purchased) valid from purchases
union all select 'monthly_sales', count(*), sum(date(mth) = mth and strftime('%d', mth) = '01') from monthly_sales
union all select 'monthly_budget', count(*), sum(date(mth) = mth and strftime('%d', mth) = '01') from monthly_budget
union all select 'orders', count(*), sum(date(ordered) = ordered) from orders
union all select 'picking_list', count(*), sum(datetime(created) = created) from picking_list
union all select 'picking_log', count(*), sum(datetime(log_time) = log_time) from picking_log
union all select 'emp start', count(*), sum(date(start_) = start_) from emp_hire_periods
union all select 'emp end', count(end_), sum(date(end_) = end_) from emp_hire_periods
union all select 'ticker', count(*), sum(date(day) = day) from ticker
union all select 'web_counter_hist', count(*), sum(date(day) = day) from web_counter_hist
union all select 'web_page_visits', count(*), sum(datetime(visit_time) = visit_time) from web_page_visits
union all select 'server_heartbeat', count(*), sum(strftime('%Y-%m-%d %H:%M', beat_time) = beat_time) from server_heartbeat
union all select 'web_devices', count(*), sum(date(day) = day) from web_devices;
-- name: monthly_sales_grid
select count(distinct product_id) products, count(distinct mth) months, count(*) rows, min(qty), max(qty), sum(qty) from monthly_sales;
-- name: monthly_budget_grid
select product_id, count(*) months, min(mth), max(mth), min(qty), max(qty), sum(qty) from monthly_budget group by 1;
-- name: purchase_schedule
-- each product is bought every other month; month parity and day-of-month by product
select product_id, count(*) n, group_concat(distinct cast(strftime('%m', purchased) as integer) % 2) month_parity, group_concat(distinct strftime('%d', purchased)) days
from purchases group by 1 order by 1;
-- name: purchase_months_per_product
select product_id, count(distinct strftime('%Y-%m', purchased)) months, count(*) n from purchases group by 1;
-- name: purchases_vs_monthly_sales_by_year
select p.yr, p.product_id, p.bought, s.sold, p.bought - s.sold diff from
 (select strftime('%Y', purchased) yr, product_id, sum(qty) bought from purchases group by 1,2) p
 join (select strftime('%Y', mth) yr, product_id, sum(qty) sold from monthly_sales group by 1,2) s on s.yr = p.yr and s.product_id = p.product_id
order by 2,1;
-- name: purchase_lagged_sales
-- does a purchase's qty equal some month's sales (+ k)?  compare qty with sum of sales in surrounding months
select p.product_id, p.purchased, p.qty, s.qty sales_same_month, s2.qty sales_next_month
from purchases p
left join monthly_sales s on s.product_id = p.product_id and s.mth = strftime('%Y-%m-01', p.purchased)
left join monthly_sales s2 on s2.product_id = p.product_id and s2.mth = strftime('%Y-%m-01', date(p.purchased, 'start of month', '+1 month'))
where p.product_id = 4040 order by p.purchased limit 18;
-- name: unit_cost
select product_id, count(*) n, round(min(cost / qty), 3) min_unit, round(max(cost / qty), 3) max_unit, round(avg(cost / qty), 3) avg_unit from purchases group by 1 order by 1;
-- name: unit_cost_by_year
select product_id, strftime('%Y', purchased) yr, round(min(cost / qty), 3) min_unit, round(max(cost / qty), 3) max_unit from purchases group by 1,2 order by 1,2;
-- name: inventory_vs_purchase
select count(*) purchases_with_inventory, sum(inv = qty) whole_lot, sum(inv < qty) part_lot, sum(inv > qty) over_purchase,
 min(purchased), max(purchased) from (select p.id, p.qty, p.purchased, sum(i.qty) inv from purchases p join inventory i on i.purchase_id = p.id group by p.id);
-- name: inventory_purchase_dates
select strftime('%Y', p.purchased) yr, count(distinct p.id) purchases, count(*) inventory_rows, sum(i.qty) qty from inventory i join purchases p on p.id = i.purchase_id group by 1;
-- name: purchases_without_inventory_dates
select min(purchased), max(purchased), count(*) from purchases where id not in (select purchase_id from inventory);
-- name: inventory_per_purchase
select n_locs, count(*) purchases from (select purchase_id, count(*) n_locs from inventory group by 1) group by 1;
-- name: inventory_qty_values
select qty, count(*) n from inventory group by 1 order by 2 desc limit 12;
-- name: inventory_lot_rule
-- lots: is each purchase split into full 48-unit cases plus one remainder?
select sum(qty = 48) full48, sum(qty < 48) partial, sum(qty > 48) over48 from inventory;
-- name: inventory_partial_per_purchase
select partials, count(*) purchases from (select purchase_id, sum(qty < 48) partials from inventory group by 1) group by 1;
-- name: inventory_by_warehouse
select l.warehouse, count(*) rows, sum(i.qty) qty from inventory i join locations l on l.id = i.location_id group by 1;
-- name: inventory_totals_vs_minimums
select m.product_id, m.qty_minimum, m.qty_purchase, (select sum(qty) from inventory i where i.product_id = m.product_id) inv from product_minimums m;
-- name: picking_vs_orderlines
select o.order_id, o.product_id, o.qty ordered, sum(l.qty) picked from orderlines o left join picking_line l on l.order_id = o.order_id and l.product_id = o.product_id
where o.order_id in (select order_id from picking_line) group by 1,2 order by 1,2;
-- name: picking_vs_inventory
-- picked qty per location vs inventory qty at that location
select l.location_id, l.product_id, sum(l.qty) picked, i.qty inv, i.qty - sum(l.qty) left_over, p.purchased
from picking_line l join inventory i on i.location_id = l.location_id join purchases p on p.id = i.purchase_id
group by l.location_id order by l.location_id;
-- name: picking_lists_same_locations
select a.line_no, a.location_id, a.qty q841, b.qty q842 from picking_line a join picking_line b on b.picklist_id = 842 and b.line_no = a.line_no where a.picklist_id = 841;
-- name: order_vs_picklist_time
select l.picklist_id, l.order_id, o.ordered, pl.created from picking_line l join orders o on o.id = l.order_id join picking_list pl on pl.id = l.picklist_id group by 1,2;
-- name: picking_log_activities
select activity, count(*) n, sum(location_id is null) loc_null, sum(pickline_no is null) line_null from picking_log group by 1;
-- name: picking_log_sequence
-- per picklist: first and last stamp, created, and pattern of activities
select g.picklist_id, pl.created, min(g.log_time) first_log, max(g.log_time) last_log, group_concat(g.activity, '') pattern
from (select * from picking_log order by picklist_id, log_time) g join picking_list pl on pl.id = g.picklist_id group by 1;
-- name: picking_log_line_order
-- do P events visit lines in line_no order?
select picklist_id, count(*) pairs, sum(pickline_no > p) increasing from (select picklist_id, pickline_no, lag(pickline_no) over (partition by picklist_id order by log_time) p from picking_log where activity = 'P') where p is not null group by 1;
-- name: picking_log_gaps
select activity, prev, count(*) n, min(gap) min_s, max(gap) max_s, round(avg(gap), 1) avg_s from (
 select activity, lag(activity) over w prev, (julianday(log_time) - julianday(lag(log_time) over w)) * 86400 gap from picking_log window w as (partition by picklist_id order by log_time))
where prev is not null group by 1,2 order by 1,2;
-- name: picking_log_loc_null
select * from picking_log where location_id is null;
-- name: orders_lines
select o.id, o.customer_id, o.ordered, count(l.id) lines, sum(l.qty) qty, sum(l.amount) amount from orders o left join orderlines l on l.order_id = o.id group by 1 order by 1;
-- name: orderline_unit_price
select product_id, count(*) n, group_concat(round(amount / qty, 4)) unit_prices from orderlines group by 1 order by 1;
-- name: orderline_id_steps
select step, count(*) from (select id - lag(id) over (order by id) step from orderlines) group by 1 order by 1;
-- name: orderline_id_vs_order
select count(*) pairs, sum(order_id >= p) nondecreasing from (select order_id, lag(order_id) over (order by id) p from orderlines) where p is not null;
-- name: monthly_orders_view_vs_sales
select mo.product_id, mo.mth, mo.qty orders_qty, ms.qty sales_qty from monthly_orders mo left join monthly_sales ms on ms.product_id = mo.product_id and ms.mth = mo.mth order by 1,2;
-- name: employees_title_vs_open_period
select e.id, e.title, group_concat(h.title, ' + ') open_titles, (select count(*) from emp_hire_periods x where x.emp_id = e.id) periods
from employees e left join emp_hire_periods h on h.emp_id = e.id and h.end_ is null group by e.id order by e.id;
-- name: hire_overlaps
select a.emp_id, a.start_, a.end_, a.title, b.start_, b.end_, b.title from emp_hire_periods a join emp_hire_periods b on a.emp_id = b.emp_id and a.start_ < b.start_ and (a.end_ is null or a.end_ > b.start_);
-- name: hire_gaps
select a.emp_id, a.end_, min(b.start_) next_start from emp_hire_periods a join emp_hire_periods b on b.emp_id = a.emp_id and b.start_ >= a.end_ group by a.emp_id, a.start_ having min(b.start_) > a.end_;
-- name: emp_hierarchy_depth
with recursive t(id, depth) as (select id, 0 from employees where supervisor_id is null union all select e.id, t.depth + 1 from employees e join t on e.supervisor_id = t.id)
select depth, count(*) from t group by 1;
-- name: picker_titles
select pl.id, pl.picker_emp_id, e.title, (select min(start_) from emp_hire_periods h where h.emp_id = e.id) first_start from picking_list pl join employees e on e.id = pl.picker_emp_id;
-- name: favorites_reviews_products
-- favourites and reviews as lists of product ids: all resolve to products?
with recursive split(cid, rest, item) as (
  select customer_id, favorite_list || ',', null from customer_favorites where favorite_list is not null
  union all select cid, substr(rest, instr(rest, ',') + 1), substr(rest, 1, instr(rest, ',') - 1) from split where rest != '')
select 'favorites' kind, count(*) items, sum(cast(item as integer) in (select id from products)) resolve from split where item is not null
union all select 'reviews', count(*), sum(cast(substr(item, 1, 4) as integer) in (select id from products)) from (
  with recursive s2(cid, rest, item) as (
    select customer_id, review_list || ',', null from customer_reviews where review_list is not null
    union all select cid, substr(rest, instr(rest, ',') + 1), substr(rest, 1, instr(rest, ',') - 1) from s2 where rest != '')
  select item from s2 where item is not null);
-- name: favorites_vs_orders
select c.id, f.favorite_list, r.review_list, (select group_concat(distinct product_id) from orderlines l join orders o on o.id = l.order_id where o.customer_id = c.id) ordered_products
from customers c left join customer_favorites f on f.customer_id = c.id left join customer_reviews r on r.customer_id = c.id;
-- name: product_alcohol_values
select sales_volume, abv, count(*) from product_alcohol group by 1,2 order by 1,2;
-- name: packaging_names_vs_volume
select p.id, p.name, pa.sales_volume from products p join product_alcohol pa on pa.product_id = p.id order by 1;
