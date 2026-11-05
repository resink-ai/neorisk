-- name: key_uniqueness
select 'customers.id' k, count(*) n, count(distinct id) d from customers
union all select 'packaging.id', count(*), count(distinct id) from packaging
union all select 'packaging_relations(p,c)', count(*), count(distinct packaging_id||'|'||contains_id) from packaging_relations
union all select 'products.id', count(*), count(distinct id) from products
union all select 'monthly_sales(p,mth)', count(*), count(distinct product_id||'|'||mth) from monthly_sales
union all select 'purchases.id', count(*), count(distinct id) from purchases
union all select 'locations.id', count(*), count(distinct id) from locations
union all select 'locations(w,a,p)', count(*), count(distinct warehouse||aisle||'|'||position) from locations
union all select 'inventory.id', count(*), count(distinct id) from inventory
union all select 'inventory(location)', count(*), count(distinct location_id) from inventory
union all select 'inventory(location,purchase)', count(*), count(distinct location_id||'|'||purchase_id) from inventory
union all select 'orders.id', count(*), count(distinct id) from orders
union all select 'orderlines.id', count(*), count(distinct id) from orderlines
union all select 'orderlines(order,product)', count(*), count(distinct order_id||'|'||product_id) from orderlines
union all select 'monthly_budget(p,mth)', count(*), count(distinct product_id||'|'||mth) from monthly_budget
union all select 'ticker(s,day)', count(*), count(distinct symbol||day) from ticker
union all select 'web_counter_hist(a,p,day)', count(*), count(distinct app_id||'|'||page_no||day) from web_counter_hist
union all select 'server_heartbeat(s,t)', count(*), count(distinct server||beat_time) from server_heartbeat
union all select 'web_page_visits(ip,time)', count(*), count(distinct client_ip||visit_time) from web_page_visits
union all select 'web_page_visits(all cols)', count(*), count(distinct client_ip||visit_time||app_id||'|'||page_no) from web_page_visits
union all select 'employees.id', count(*), count(distinct id) from employees
union all select 'emp_hire_periods(e,start)', count(*), count(distinct emp_id||start_) from emp_hire_periods
union all select 'picking_line(l,no)', count(*), count(distinct picklist_id||'|'||line_no) from picking_line
union all select 'picking_log(l,time)', count(*), count(distinct picklist_id||log_time) from picking_log;
-- name: id_ranges
select 'purchases' t, min(id), max(id), count(*), max(id)-min(id)+1 span from purchases
union all select 'inventory', min(id), max(id), count(*), max(id)-min(id)+1 from inventory
union all select 'orders', min(id), max(id), count(*), max(id)-min(id)+1 from orders
union all select 'orderlines', min(id), max(id), count(*), max(id)-min(id)+1 from orderlines
union all select 'locations', min(id), max(id), count(*), max(id)-min(id)+1 from locations
union all select 'employees', min(id), max(id), count(*), max(id)-min(id)+1 from employees;
-- name: purchase_id_steps
select step, count(*) n from (select id - lag(id) over (order by id) step from purchases) group by 1 order by 2 desc;
-- name: inventory_id_steps
select step, count(*) n from (select id - lag(id) over (order by id) step from inventory) group by 1 order by 2 desc;
-- name: purchase_id_vs_date
select count(*) pairs, sum(purchased >= p) nondecreasing, sum(purchased < p) decreasing from (select purchased, lag(purchased) over (order by id) p from purchases) where p is not null;
-- name: purchase_id_vs_date_breaks
select id, purchased, prev_id, prev_purchased from (select id, purchased, lag(id) over (order by id) prev_id, lag(purchased) over (order by id) prev_purchased from purchases) where purchased < prev_purchased;
-- name: fk_orphans
select 'packaging_relations.packaging_id' fk, count(*) orphans from packaging_relations where packaging_id not in (select id from packaging)
union all select 'packaging_relations.contains_id', count(*) from packaging_relations where contains_id not in (select id from packaging)
union all select 'products.group_id', count(*) from products where group_id not in (select id from product_groups)
union all select 'monthly_sales.product_id', count(*) from monthly_sales where product_id not in (select id from products)
union all select 'purchases.brewery_id', count(*) from purchases where brewery_id not in (select id from breweries)
union all select 'purchases.product_id', count(*) from purchases where product_id not in (select id from products)
union all select 'product_alcohol.product_id', count(*) from product_alcohol where product_id not in (select id from products)
union all select 'customer_favorites.customer_id', count(*) from customer_favorites where customer_id not in (select id from customers)
union all select 'customer_reviews.customer_id', count(*) from customer_reviews where customer_id not in (select id from customers)
union all select 'inventory.location_id', count(*) from inventory where location_id not in (select id from locations)
union all select 'inventory.product_id', count(*) from inventory where product_id not in (select id from products)
union all select 'inventory.purchase_id', count(*) from inventory where purchase_id not in (select id from purchases)
union all select 'inventory.product = purchase.product', count(*) from inventory i join purchases p on p.id = i.purchase_id where p.product_id != i.product_id
union all select 'orders.customer_id', count(*) from orders where customer_id not in (select id from customers)
union all select 'orderlines.order_id', count(*) from orderlines where order_id not in (select id from orders)
union all select 'orderlines.product_id', count(*) from orderlines where product_id not in (select id from products)
union all select 'monthly_budget.product_id', count(*) from monthly_budget where product_id not in (select id from products)
union all select 'product_minimums.product_id', count(*) from product_minimums where product_id not in (select id from products)
union all select 'ticker.symbol', count(*) from ticker where symbol not in (select symbol from stock)
union all select 'web_pages.app_id', count(*) from web_pages where app_id not in (select id from web_apps)
union all select 'web_counter_hist.page', count(*) from web_counter_hist h where not exists (select 1 from web_pages p where p.app_id=h.app_id and p.page_no=h.page_no)
union all select 'web_page_visits.page', count(*) from web_page_visits h where not exists (select 1 from web_pages p where p.app_id=h.app_id and p.page_no=h.page_no)
union all select 'employees.supervisor_id', count(*) from employees where supervisor_id not in (select id from employees)
union all select 'emp_hire_periods.emp_id', count(*) from emp_hire_periods where emp_id not in (select id from employees)
union all select 'picking_list.picker_emp_id', count(*) from picking_list where picker_emp_id not in (select id from employees)
union all select 'picking_line.picklist_id', count(*) from picking_line where picklist_id not in (select id from picking_list)
union all select 'picking_line.location_id', count(*) from picking_line where location_id not in (select id from locations)
union all select 'picking_line.order_id', count(*) from picking_line where order_id not in (select id from orders)
union all select 'picking_line.product_id', count(*) from picking_line where product_id not in (select id from products)
union all select 'picking_line (order,product) in orderlines', count(*) from picking_line l where not exists (select 1 from orderlines o where o.order_id=l.order_id and o.product_id=l.product_id)
union all select 'picking_log.picklist_id', count(*) from picking_log where picklist_id not in (select id from picking_list)
union all select 'picking_log.location_id', count(*) from picking_log where location_id not in (select id from locations)
union all select 'picking_log.(list,pickline_no)', count(*) from picking_log g where pickline_no is not null and not exists (select 1 from picking_line l where l.picklist_id=g.picklist_id and l.line_no=g.pickline_no)
union all select 'picking_log P location = line location', count(*) from picking_log g join picking_line l on l.picklist_id=g.picklist_id and l.line_no=g.pickline_no where g.location_id != l.location_id;
-- name: coverage
select 'products in purchases' what, count(distinct product_id) n from purchases
union all select 'breweries in purchases', count(distinct brewery_id) from purchases
union all select 'products in monthly_sales', count(distinct product_id) from monthly_sales
union all select 'products in inventory', count(distinct product_id) from inventory
union all select 'products in orderlines', count(distinct product_id) from orderlines
union all select 'products in monthly_budget', count(distinct product_id) from monthly_budget
union all select 'purchases in inventory', count(distinct purchase_id) from inventory
union all select 'locations in inventory', count(distinct location_id) from inventory
union all select 'locations in picking_line', count(distinct location_id) from picking_line
union all select 'locations in picking_line not in inventory', count(distinct location_id) from picking_line where location_id not in (select location_id from inventory)
union all select 'customers with orders', count(distinct customer_id) from orders
union all select 'orders picked', count(distinct order_id) from picking_line
union all select 'employees with hire periods', count(distinct emp_id) from emp_hire_periods
union all select 'employees who pick', count(distinct picker_emp_id) from picking_list
union all select 'pages visited', count(distinct page_no) from web_page_visits
union all select 'pages in counter hist', count(distinct page_no) from web_counter_hist
union all select 'packaging used as container', count(distinct packaging_id) from packaging_relations
union all select 'packaging used as content', count(distinct contains_id) from packaging_relations
union all select 'packaging never related', count(*) from packaging where id not in (select packaging_id from packaging_relations) and id not in (select contains_id from packaging_relations);
-- name: products_by_brewery
select brewery_id, product_id, count(*) purchases, min(purchased), max(purchased) from purchases group by 1,2 order by 1,2;
-- name: products_multi_brewery
select product_id, count(distinct brewery_id) from purchases group by 1 having count(distinct brewery_id) > 1;
