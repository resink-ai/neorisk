-- name: locations_is_grid
-- locations rebuilt from a generated grid: 2 warehouses x aisles A-D x positions 1-32, id = row_number
with recursive w(x) as (select 1 union all select x + 1 from w where x < 2),
 a(x) as (select 'A' union all select 'B' union all select 'C' union all select 'D'),
 p(x) as (select 1 union all select x + 1 from p where x < 32),
 g as (select row_number() over (order by w.x, a.x, p.x) id, w.x warehouse, a.x aisle, p.x position from w, a, p)
select (select count(*) from g) grid_rows,
 (select count(*) from (select * from g except select id, warehouse, aisle, position from locations)) grid_not_in_src,
 (select count(*) from (select id, warehouse, aisle, position from locations except select * from g)) src_not_in_grid;
-- name: locations_used
select l.warehouse, l.aisle, count(*) locs, count(i.id) with_inventory, (select count(distinct location_id) from picking_line pl join locations x on x.id = pl.location_id where x.warehouse = l.warehouse and x.aisle = l.aisle) picked_from
from locations l left join inventory i on i.location_id = l.id group by 1,2 order by 1,2;
-- name: devices_vs_demographics_totals
select d.day, d.pc + d.tablet + d.phone devices_total, g.m_tw_cnt + g.m_fb_cnt + g.f_tw_cnt + g.f_fb_cnt demo_cnt_total, g.m_tw_qty + g.m_fb_qty + g.f_tw_qty + g.f_fb_qty demo_qty_total
from web_devices d join web_demographics g on g.day = d.day;
-- name: counter_monotonic
select page_no, count(*) days, sum(counter >= p) nondecreasing, sum(counter < p) decreasing, min(counter - p) min_delta, max(counter - p) max_delta, min(day), max(day)
from (select page_no, day, counter, lag(counter) over (partition by app_id, page_no order by day) p from web_counter_hist) where p is not null group by 1;
-- name: counter_first_last
select page_no, min(counter) first, max(counter) last from web_counter_hist group by 1;
-- name: counter_days_complete
select page_no, count(*), julianday(max(day)) - julianday(min(day)) + 1 span from web_counter_hist group by 1;
-- name: counter_delta_on_visit_day
select h.page_no, h.counter - (select counter from web_counter_hist x where x.app_id = h.app_id and x.page_no = h.page_no and x.day = date(h.day, '-1 day')) delta_0420,
 (select count(*) from web_page_visits v where v.page_no = h.page_no) visits_0420
from web_counter_hist h where h.day = '2019-04-20';
-- name: visits_per_ip
select client_ip, count(*), min(visit_time), max(visit_time) from web_page_visits group by 1;
-- name: visit_gaps
select client_ip, min(g), max(g), count(*) from (select client_ip, (julianday(visit_time) - julianday(lag(visit_time) over (partition by client_ip order by visit_time))) * 86400 g from web_page_visits) where g is not null group by 1;
-- name: visit_rowid_order
select count(*) pairs, sum(visit_time > p) increasing from (select visit_time, lag(visit_time) over (order by rowid) p from web_page_visits) where p is not null;
-- name: heartbeat_gaps
select server, g minutes, count(*) n from (select server, cast(round((julianday(beat_time) - julianday(lag(beat_time) over (partition by server order by beat_time))) * 1440) as integer) g from server_heartbeat) where g is not null group by 1,2 order by 1,2;
-- name: ticker_weekdays
select strftime('%w', day) dow, count(*) from ticker group by 1;
-- name: ticker_moves
select sum(price > p) up, sum(price < p) down, sum(price = p) flat, min(price), max(price) from (select price, lag(price) over (order by day) p from ticker) where p is not null;
-- name: ticker_price_decimals
select price, printf('%.17g', price) stored from ticker where price != round(price, 1);
-- name: views_run
select 'customer_order_products' v, count(*) from customer_order_products
union all select 'customer_order_products_obj', count(*) from customer_order_products_obj
union all select 'web_page_counter_hist', count(*) from web_page_counter_hist
union all select 'monthly_orders', count(*) from monthly_orders
union all select 'inventory_totals', count(*) from inventory_totals
union all select 'inventory_with_dims', count(*) from inventory_with_dims
union all select 'yearly_sales', count(*) from yearly_sales
union all select 'total_sales', count(*) from total_sales
union all select 'brewery_products', count(*) from brewery_products
union all select 'purchases_with_dims', count(*) from purchases_with_dims;
-- name: customer_order_products_obj_sample
select * from customer_order_products_obj limit 1;
-- name: real_columns_integral
select 'orderlines.amount' c, count(*) n, sum(amount = cast(amount as integer)) integral from orderlines
union all select 'orderlines.qty', count(*), sum(qty = cast(qty as integer)) from orderlines
union all select 'purchases.cost', count(*), sum(cost = cast(cost as integer)) from purchases
union all select 'inventory.qty', count(*), sum(qty = cast(qty as integer)) from inventory
union all select 'picking_line.qty', count(*), sum(qty = cast(qty as integer)) from picking_line
union all select 'monthly_budget.qty', count(*), sum(qty = cast(qty as integer)) from monthly_budget
union all select 'product_minimums.qty_minimum', count(*), sum(qty_minimum = cast(qty_minimum as integer)) from product_minimums
union all select 'product_alcohol.abv x2', count(*), sum(abv * 2 = cast(abv * 2 as integer)) from product_alcohol
union all select 'ticker.price x10', count(*), sum(abs(price * 10 - round(price * 10)) < 1e-9) from ticker;
-- name: inventory_id_vs_purchase
-- inventory id order vs (purchase id): ids rise with purchase?
select count(*) pairs, sum(purchase_id >= p) nondecreasing from (select purchase_id, lag(purchase_id) over (order by id) p from inventory) where p is not null;
-- name: inventory_id_breaks
select id, purchase_id, prev_purchase from (select id, purchase_id, lag(purchase_id) over (order by id) prev_purchase from inventory) where purchase_id < prev_purchase;
-- name: monthly_sales_zero
select count(*) zero_months from monthly_sales where qty = 0;
