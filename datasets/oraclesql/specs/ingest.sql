-- oraclesql: source tables → events (refdata ingest). Money is in cents.
-- Rule times: masters at 2016-01-01 (the first purchase); employees at their first hire
-- start, else 2016-01-01; lots at their purchase's date; budgets at Jan 1 of their year;
-- pick lines at their picklist's creation; snapshot rows at N = 2019-05-02.
-- locations is a generated grid (build.sql); the 5 empty tables and the 11 views have no rows.

-- entity: product_groups
SELECT CAST(id AS TEXT) AS ext_id, '2016-01-01 00:00:00' AS created_at, name
FROM product_groups ORDER BY id;

-- entity: products
SELECT CAST(p.id AS TEXT) AS ext_id, '2016-01-01 00:00:00' AS created_at, p.name,
       CAST(p.group_id AS TEXT) AS group_id, CAST(a.sales_volume AS INTEGER) AS sales_volume,
       a.abv
FROM products p JOIN product_alcohol a ON a.product_id = p.id ORDER BY p.id;

-- entity: breweries
SELECT CAST(id AS TEXT) AS ext_id, '2016-01-01 00:00:00' AS created_at, name
FROM breweries ORDER BY id;

-- entity: customers
SELECT CAST(id AS TEXT) AS ext_id, '2016-01-01 00:00:00' AS created_at, name
FROM customers ORDER BY id;

-- entity: packaging
SELECT CAST(id AS TEXT) AS ext_id, '2016-01-01 00:00:00' AS created_at, name
FROM packaging ORDER BY id;

-- entity: packaging_relations
SELECT packaging_id || ':' || contains_id AS ext_id, '2016-01-01 00:00:00' AS created_at,
       CAST(packaging_id AS TEXT) AS packaging_id, CAST(contains_id AS TEXT) AS contains_id, qty
FROM packaging_relations ORDER BY packaging_id, contains_id;

-- entity: employees
SELECT CAST(e.id AS TEXT) AS ext_id,
       coalesce((SELECT min(h.start_) FROM emp_hire_periods h WHERE h.emp_id = e.id),
                '2016-01-01') || ' 00:00:00' AS created_at,
       e.name
FROM employees e ORDER BY e.id;

-- entity: web_apps
SELECT CAST(id AS TEXT) AS ext_id, '2016-01-01 00:00:00' AS created_at, name
FROM web_apps ORDER BY id;

-- entity: web_pages
SELECT app_id || ':' || page_no AS ext_id, '2016-01-01 00:00:00' AS created_at,
       CAST(app_id AS TEXT) AS app_id, page_no, friendly_url
FROM web_pages ORDER BY app_id, page_no;

-- entity: stock
SELECT symbol AS ext_id, '2016-01-01 00:00:00' AS created_at, company FROM stock ORDER BY symbol;

-- entity: channels_dim
SELECT CAST(id AS TEXT) AS ext_id, '2016-01-01 00:00:00' AS created_at, name, shortcut
FROM channels_dim ORDER BY id;

-- entity: gender_dim
SELECT letter AS ext_id, '2016-01-01 00:00:00' AS created_at, name
FROM gender_dim ORDER BY letter;

-- event: purchase_received owner=brewery_id ord=purchase_id
SELECT purchased || ' 00:00:00' AS event_time, CAST(brewery_id AS TEXT) AS brewery_id,
       id AS purchase_id, CAST(product_id AS TEXT) AS product_id, qty,
       CAST(round(cost * 100) AS INTEGER) AS cost
FROM purchases ORDER BY id;

-- event: lot_stored owner=product_id ord=inventory_id
SELECT p.purchased || ' 00:00:00' AS event_time, CAST(i.product_id AS TEXT) AS product_id,
       i.id AS inventory_id, i.location_id, i.purchase_id, CAST(i.qty AS INTEGER) AS qty
FROM inventory i JOIN purchases p ON p.id = i.purchase_id ORDER BY i.id;

-- event: monthly_sales_reported owner=product_id
SELECT mth || ' 00:00:00' AS event_time, CAST(product_id AS TEXT) AS product_id, qty
FROM monthly_sales ORDER BY mth, product_id;

-- event: budget_set owner=product_id
SELECT strftime('%Y-01-01 00:00:00', mth) AS event_time, CAST(product_id AS TEXT) AS product_id,
       mth, CAST(qty AS INTEGER) AS qty
FROM monthly_budget ORDER BY product_id, mth;

-- event: order_placed owner=customer_id ord=order_id
SELECT ordered || ' 00:00:00' AS event_time, CAST(customer_id AS TEXT) AS customer_id,
       id AS order_id
FROM orders ORDER BY id;

-- event: order_line_added owner=customer_id ord=orderline_id
SELECT o.ordered || ' 00:00:00' AS event_time, CAST(o.customer_id AS TEXT) AS customer_id,
       l.id AS orderline_id, l.order_id, CAST(l.product_id AS TEXT) AS product_id,
       CAST(l.qty AS INTEGER) AS qty, CAST(round(l.amount * 100) AS INTEGER) AS amount
FROM orderlines l JOIN orders o ON o.id = l.order_id ORDER BY l.id;

-- event: picklist_created owner=picker_emp_id ord=picklist_id
SELECT created AS event_time, CAST(picker_emp_id AS TEXT) AS picker_emp_id, id AS picklist_id
FROM picking_list ORDER BY id;

-- event: pick_line_planned owner=picker_emp_id ord=line_no
SELECT pl.created AS event_time, CAST(pl.picker_emp_id AS TEXT) AS picker_emp_id,
       l.picklist_id, l.line_no, l.location_id, l.order_id,
       CAST(l.product_id AS TEXT) AS product_id, CAST(l.qty AS INTEGER) AS qty
FROM picking_line l JOIN picking_list pl ON pl.id = l.picklist_id
ORDER BY l.picklist_id, l.line_no;

-- event: picker_arrived owner=picker_emp_id
SELECT g.log_time AS event_time, CAST(pl.picker_emp_id AS TEXT) AS picker_emp_id,
       g.picklist_id, g.location_id, g.pickline_no
FROM picking_log g JOIN picking_list pl ON pl.id = g.picklist_id WHERE g.activity = 'A'
ORDER BY g.picklist_id, g.log_time;

-- event: line_picked owner=picker_emp_id
SELECT g.log_time AS event_time, CAST(pl.picker_emp_id AS TEXT) AS picker_emp_id,
       g.picklist_id, g.location_id, g.pickline_no
FROM picking_log g JOIN picking_list pl ON pl.id = g.picklist_id WHERE g.activity = 'P'
ORDER BY g.picklist_id, g.log_time;

-- event: picker_departed owner=picker_emp_id
SELECT g.log_time AS event_time, CAST(pl.picker_emp_id AS TEXT) AS picker_emp_id,
       g.picklist_id, g.location_id, g.pickline_no
FROM picking_log g JOIN picking_list pl ON pl.id = g.picklist_id WHERE g.activity = 'D'
ORDER BY g.picklist_id, g.log_time;

-- event: hire_period_started owner=employee_id
SELECT start_ || ' 00:00:00' AS event_time, CAST(emp_id AS TEXT) AS employee_id, title
FROM emp_hire_periods ORDER BY emp_id, start_;

-- event: hire_period_ended owner=employee_id
SELECT end_ || ' 00:00:00' AS event_time, CAST(emp_id AS TEXT) AS employee_id, start_ AS start
FROM emp_hire_periods WHERE end_ IS NOT NULL ORDER BY emp_id, start_;

-- event: page_counter_read owner=page_id
SELECT day || ' 00:00:00' AS event_time, app_id || ':' || page_no AS page_id, counter
FROM web_counter_hist ORDER BY app_id, page_no, day;

-- event: page_visited owner=client_ip ord=src_rowid
SELECT visit_time AS event_time, client_ip, app_id || ':' || page_no AS page_id,
       rowid AS src_rowid
FROM web_page_visits ORDER BY rowid;

-- event: heartbeat_received owner=server
SELECT beat_time || ':00' AS event_time, server FROM server_heartbeat ORDER BY server, beat_time;

-- event: device_counts_reported owner=app_id
SELECT day || ' 00:00:00' AS event_time, '542' AS app_id, pc, tablet, phone
FROM web_devices ORDER BY day;

-- event: demographics_reported owner=app_id
SELECT day || ' 00:00:00' AS event_time, '542' AS app_id, m_tw_cnt, m_tw_qty, m_fb_cnt,
       m_fb_qty, f_tw_cnt, f_tw_qty, f_fb_cnt, f_fb_qty
FROM web_demographics ORDER BY day;

-- event: price_quoted owner=stock_id
SELECT day || ' 00:00:00' AS event_time, symbol AS stock_id, price
FROM ticker ORDER BY symbol, day;

-- event: customers_snapshot owner=customer_id
SELECT '2019-05-02 00:00:00' AS event_time, CAST(c.id AS TEXT) AS customer_id,
       f.favorite_list, r.review_list
FROM customers c JOIN customer_favorites f ON f.customer_id = c.id
JOIN customer_reviews r ON r.customer_id = c.id ORDER BY c.id;

-- event: employees_snapshot owner=employee_id
SELECT '2019-05-02 00:00:00' AS event_time, CAST(id AS TEXT) AS employee_id, title,
       CAST(supervisor_id AS TEXT) AS supervisor_id
FROM employees ORDER BY id;

-- event: products_snapshot owner=product_id
SELECT '2019-05-02 00:00:00' AS event_time, CAST(product_id AS TEXT) AS product_id,
       CAST(qty_minimum AS INTEGER) AS qty_minimum, CAST(qty_purchase AS INTEGER) AS qty_purchase
FROM product_minimums ORDER BY product_id;
