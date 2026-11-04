-- oraclesql: events → source tables (refdata rebuild, DuckDB).
-- Dates and times are formatted back from event_time; money is cents / 100.0; locations is
-- the book's generated grid; the 5 empty tables are typed empty selects.

-- table: customers
SELECT CAST(ext_id AS BIGINT) AS id, name FROM customers;

-- table: conway_gen_zero
SELECT NULL::BIGINT AS x, NULL::BIGINT AS y, NULL::BIGINT AS alive WHERE false;

-- table: web_devices
SELECT strftime(d.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS day, d.pc, d.tablet, d.phone
FROM device_counts_reported d;

-- table: web_demographics
SELECT strftime(d.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS day, d.m_tw_cnt, d.m_tw_qty,
       d.m_fb_cnt, d.m_fb_qty, d.f_tw_cnt, d.f_tw_qty, d.f_fb_cnt, d.f_fb_qty
FROM demographics_reported d;

-- table: channels_dim
SELECT CAST(ext_id AS BIGINT) AS id, name, shortcut FROM channels_dim;

-- table: gender_dim
SELECT ext_id AS letter, name FROM gender_dim;

-- table: packaging
SELECT CAST(ext_id AS BIGINT) AS id, name FROM packaging;

-- table: packaging_relations
SELECT CAST(a.ext_id AS BIGINT) AS packaging_id, CAST(b.ext_id AS BIGINT) AS contains_id, r.qty
FROM packaging_relations r JOIN packaging a ON a.packaging_key = r.packaging_id
JOIN packaging b ON b.packaging_key = r.contains_id;

-- table: product_groups
SELECT CAST(ext_id AS BIGINT) AS id, name FROM product_groups;

-- table: products
SELECT CAST(p.ext_id AS BIGINT) AS id, p.name, CAST(g.ext_id AS BIGINT) AS group_id
FROM products p JOIN product_groups g ON g.group_key = p.group_id;

-- table: monthly_sales
SELECT CAST(p.ext_id AS BIGINT) AS product_id,
       strftime(m.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS mth, m.qty
FROM monthly_sales_reported m JOIN products p ON p.product_key = m.product_id;

-- table: breweries
SELECT CAST(ext_id AS BIGINT) AS id, name FROM breweries;

-- table: purchases
SELECT e.purchase_id AS id, strftime(e.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS purchased,
       CAST(b.ext_id AS BIGINT) AS brewery_id, CAST(p.ext_id AS BIGINT) AS product_id, e.qty,
       e.cost / 100.0 AS cost
FROM purchase_received e JOIN breweries b ON b.brewery_key = e.brewery_id
JOIN products p ON p.product_key = e.product_id;

-- table: product_alcohol
SELECT CAST(ext_id AS BIGINT) AS product_id, CAST(sales_volume AS DOUBLE) AS sales_volume, abv
FROM products;

-- table: customer_favorites
SELECT CAST(c.ext_id AS BIGINT) AS customer_id, s.favorite_list
FROM customers_snapshot s JOIN customers c ON c.customer_key = s.customer_id;

-- table: customer_reviews
SELECT CAST(c.ext_id AS BIGINT) AS customer_id, s.review_list
FROM customers_snapshot s JOIN customers c ON c.customer_key = s.customer_id;

-- table: locations
-- The book's grid: 2 warehouses x aisles A-D x positions 1-32, id in that order.
SELECT CAST(row_number() OVER (ORDER BY w, a, p) AS BIGINT) AS id, w AS warehouse, a AS aisle,
       p AS position
FROM range(1, 3) t1(w), (VALUES ('A'), ('B'), ('C'), ('D')) t2(a), range(1, 33) t3(p);

-- table: inventory
SELECT e.inventory_id AS id, e.location_id, CAST(p.ext_id AS BIGINT) AS product_id,
       e.purchase_id, CAST(e.qty AS DOUBLE) AS qty
FROM lot_stored e JOIN products p ON p.product_key = e.product_id;

-- table: orders
SELECT e.order_id AS id, CAST(c.ext_id AS BIGINT) AS customer_id,
       strftime(e.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS ordered, NULL::VARCHAR AS delivery
FROM order_placed e JOIN customers c ON c.customer_key = e.customer_id;

-- table: orderlines
SELECT e.orderline_id AS id, e.order_id, CAST(p.ext_id AS BIGINT) AS product_id,
       CAST(e.qty AS DOUBLE) AS qty, e.amount / 100.0 AS amount
FROM order_line_added e JOIN products p ON p.product_key = e.product_id;

-- table: monthly_budget
SELECT CAST(p.ext_id AS BIGINT) AS product_id, e.mth, CAST(e.qty AS DOUBLE) AS qty
FROM budget_set e JOIN products p ON p.product_key = e.product_id;

-- table: product_minimums
SELECT CAST(p.ext_id AS BIGINT) AS product_id, CAST(e.qty_minimum AS DOUBLE) AS qty_minimum,
       CAST(e.qty_purchase AS DOUBLE) AS qty_purchase
FROM products_snapshot e JOIN products p ON p.product_key = e.product_id;

-- table: stock
SELECT ext_id AS symbol, company FROM stock;

-- table: ticker
SELECT s.ext_id AS symbol, strftime(e.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS day, e.price
FROM price_quoted e JOIN stock s ON s.stock_key = e.stock_id;

-- table: web_apps
SELECT CAST(ext_id AS BIGINT) AS id, name FROM web_apps;

-- table: web_pages
SELECT CAST(a.ext_id AS BIGINT) AS app_id, w.page_no, w.friendly_url
FROM web_pages w JOIN web_apps a ON a.app_key = w.app_id;

-- table: web_counter_hist
SELECT CAST(a.ext_id AS BIGINT) AS app_id, w.page_no,
       strftime(e.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS day, e.counter
FROM page_counter_read e JOIN web_pages w ON w.page_key = e.page_id
JOIN web_apps a ON a.app_key = w.app_id;

-- table: server_heartbeat
-- beat_time has no seconds in the source.
SELECT e.server, strftime(e.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M') AS beat_time
FROM heartbeat_received e;

-- table: web_page_visits
SELECT e.client_ip, strftime(e.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS visit_time,
       CAST(a.ext_id AS BIGINT) AS app_id, w.page_no
FROM page_visited e JOIN web_pages w ON w.page_key = e.page_id
JOIN web_apps a ON a.app_key = w.app_id;

-- table: employees
SELECT CAST(e.ext_id AS BIGINT) AS id, e.name, s.title, CAST(b.ext_id AS BIGINT) AS supervisor_id
FROM employees e JOIN employees_snapshot s ON s.employee_id = e.employee_key
LEFT JOIN employees b ON b.employee_key = s.supervisor_id;

-- table: emp_hire_periods
SELECT CAST(e.ext_id AS BIGINT) AS emp_id,
       strftime(h.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS start_,
       strftime(x.event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS end_, h.title
FROM hire_period_started h JOIN employees e ON e.employee_key = h.employee_id
LEFT JOIN hire_period_ended x ON x.employee_id = h.employee_id
 AND x.start = strftime(h.event_time AT TIME ZONE 'UTC', '%Y-%m-%d');

-- table: picking_list
SELECT e.picklist_id AS id, strftime(e.event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS created,
       CAST(m.ext_id AS BIGINT) AS picker_emp_id
FROM picklist_created e JOIN employees m ON m.employee_key = e.picker_emp_id;

-- table: picking_line
SELECT e.picklist_id, e.line_no, e.location_id, e.order_id, CAST(p.ext_id AS BIGINT) AS product_id,
       CAST(e.qty AS DOUBLE) AS qty
FROM pick_line_planned e JOIN products p ON p.product_key = e.product_id;

-- table: picking_log
SELECT picklist_id, strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS log_time,
       activity, location_id, pickline_no
FROM (SELECT *, 'A' AS activity FROM picker_arrived
      UNION ALL BY NAME SELECT *, 'P' AS activity FROM line_picked
      UNION ALL BY NAME SELECT *, 'D' AS activity FROM picker_departed);

-- table: id_name_type
SELECT NULL::BIGINT AS id, NULL::VARCHAR AS name WHERE false;

-- table: id_name_coll_type
SELECT NULL::BIGINT AS collection_id WHERE false;

-- table: id_name_coll_entries
SELECT NULL::BIGINT AS collection_id, NULL::BIGINT AS id, NULL::VARCHAR AS name WHERE false;

-- table: favorite_coll_type
SELECT NULL::BIGINT AS id WHERE false;
