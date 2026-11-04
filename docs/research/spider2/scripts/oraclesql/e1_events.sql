-- name: event_counts
-- proposed events, their source counts and how their time is set (natural / reported = period date / rule)
with e(ev, n, timing) as (
 select 'purchase_received', (select count(*) from purchases), 'natural'
 union all select 'lot_stored', (select count(*) from inventory), 'rule: purchase date'
 union all select 'monthly_sales_reported', (select count(*) from monthly_sales), 'reported: mth'
 union all select 'budget_set', (select count(*) from monthly_budget), 'rule: Jan 1 of mth year'
 union all select 'order_placed', (select count(*) from orders), 'natural'
 union all select 'order_line_added', (select count(*) from orderlines), 'natural (order time)'
 union all select 'picklist_created', (select count(*) from picking_list), 'natural'
 union all select 'pick_line_planned', (select count(*) from picking_line), 'rule: picklist created'
 union all select 'picker_arrived', (select count(*) from picking_log where activity = 'A'), 'natural'
 union all select 'line_picked', (select count(*) from picking_log where activity = 'P'), 'natural'
 union all select 'picker_departed', (select count(*) from picking_log where activity = 'D'), 'natural'
 union all select 'hire_period_started', (select count(*) from emp_hire_periods), 'natural'
 union all select 'hire_period_ended', (select count(end_) from emp_hire_periods), 'natural'
 union all select 'page_counter_read', (select count(*) from web_counter_hist), 'reported: day'
 union all select 'page_visited', (select count(*) from web_page_visits), 'natural'
 union all select 'heartbeat_received', (select count(*) from server_heartbeat), 'natural'
 union all select 'device_counts_reported', (select count(*) from web_devices), 'reported: day'
 union all select 'demographics_reported', (select count(*) from web_demographics), 'reported: day'
 union all select 'price_quoted', (select count(*) from ticker), 'natural (daily close)'
 union all select 'customers_snapshot', (select count(*) from customers), 'rule: N'
 union all select 'employees_snapshot', (select count(*) from employees), 'rule: N'
 union all select 'products_snapshot', (select count(*) from product_minimums), 'rule: N')
select ev, n, timing from e union all select 'TOTAL (' || count(*) || ' types)', sum(n), '' from e
union all select 'natural', sum(n), '' from e where timing like 'natural%'
union all select 'reported', sum(n), '' from e where timing like 'reported%'
union all select 'rule', sum(n), '' from e where timing like 'rule%';
-- name: entity_counts
select 'product_groups' e, count(*) n from product_groups union all select 'products (+ product_alcohol, product_minimums)', count(*) from products
union all select 'breweries', count(*) from breweries union all select 'customers (+ favorites, reviews)', count(*) from customers
union all select 'packaging', count(*) from packaging union all select 'packaging_relations', count(*) from packaging_relations
union all select 'employees', count(*) from employees union all select 'web_apps', count(*) from web_apps
union all select 'web_pages', count(*) from web_pages union all select 'stock', count(*) from stock
union all select 'channels_dim', count(*) from channels_dim union all select 'gender_dim', count(*) from gender_dim;
-- name: one_to_one_folds
select 'products with product_alcohol' k, count(*) from products where id in (select product_id from product_alcohol)
union all select 'customers with favorites row', count(*) from customers where id in (select customer_id from customer_favorites)
union all select 'customers with reviews row', count(*) from customers where id in (select customer_id from customer_reviews)
union all select 'products with minimums', count(*) from products where id in (select product_id from product_minimums);
-- name: time_ties
select 'purchases same day' k, count(*) from (select purchased from purchases group by 1 having count(*) > 1)
union all select 'orders same day', count(*) from (select ordered from orders group by 1 having count(*) > 1)
union all select 'visits same second', count(*) from (select visit_time from web_page_visits group by 1 having count(*) > 1)
union all select 'heartbeats same minute across servers', count(*) from (select beat_time from server_heartbeat group by 1 having count(*) > 1)
union all select 'picking_log same second across lists', count(*) from (select log_time from picking_log group by 1 having count(*) > 1);
-- name: snapshot_N
select max(t) N from (select max(purchased) t from purchases union all select max(ordered) from orders union all select max(log_time) from picking_log
 union all select max(start_) from emp_hire_periods union all select max(end_) from emp_hire_periods union all select max(day) from ticker
 union all select max(day) from web_counter_hist union all select max(visit_time) from web_page_visits union all select max(beat_time) from server_heartbeat
 union all select max(day) from web_devices union all select max(mth) from monthly_sales);
-- name: employee_created_at
select e.id, (select min(start_) from emp_hire_periods h where h.emp_id = e.id) first_start from employees e order by 1;
-- name: subcatalog_rows
select 'brewery core' g, (select count(*) from product_groups) + (select count(*) from products) + (select count(*) from breweries) + (select count(*) from purchases)
 + (select count(*) from product_alcohol) + (select count(*) from customers) + (select count(*) from customer_favorites) + (select count(*) from customer_reviews)
 + (select count(*) from locations) + (select count(*) from inventory) + (select count(*) from orders) + (select count(*) from orderlines)
 + (select count(*) from monthly_sales) + (select count(*) from monthly_budget) + (select count(*) from product_minimums)
 + (select count(*) from packaging) + (select count(*) from packaging_relations) n
union all select 'warehouse staff and picking', (select count(*) from employees) + (select count(*) from emp_hire_periods) + (select count(*) from picking_list) + (select count(*) from picking_line) + (select count(*) from picking_log)
union all select 'web analytics', (select count(*) from web_apps) + (select count(*) from web_pages) + (select count(*) from web_counter_hist) + (select count(*) from web_page_visits)
 + (select count(*) from server_heartbeat) + (select count(*) from web_devices) + (select count(*) from web_demographics) + (select count(*) from channels_dim) + (select count(*) from gender_dim)
union all select 'stock ticker', (select count(*) from stock) + (select count(*) from ticker)
union all select 'empty (conway, Oracle types)', (select count(*) from conway_gen_zero) + (select count(*) from id_name_type) + (select count(*) from id_name_coll_type) + (select count(*) from id_name_coll_entries) + (select count(*) from favorite_coll_type);
