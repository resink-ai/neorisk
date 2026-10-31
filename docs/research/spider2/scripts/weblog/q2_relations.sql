-- Cross-table relations: shared sessions and users, and whether variant tables are functions of base tables.
-- name: session_tables
-- every session id, the tables it appears in, and the user ids it carries there
WITH s(t, session, user_id, d) AS (
  SELECT 'action_log', session, user_id, substr(stamp,1,10) FROM action_log
  UNION ALL SELECT 'action_log_with_ip', session, user_id, substr(stamp,1,10) FROM action_log_with_ip
  UNION ALL SELECT 'dup_action_log', session, user_id, substr(stamp,1,10) FROM dup_action_log
  UNION ALL SELECT 'invalid_action_log', session, user_id, substr(stamp,1,10) FROM invalid_action_log
  UNION ALL SELECT 'access_log(ok rows)', session, user_id, substr(stamp,1,10) FROM access_log WHERE datetime(stamp) IS NOT NULL
  UNION ALL SELECT 'access_log(shifted: user_id col)', user_id, NULL, substr(session,1,10) FROM access_log WHERE datetime(stamp) IS NULL
  UNION ALL SELECT 'activity_log', session, NULL, substr(stamp,1,10) FROM activity_log
  UNION ALL SELECT 'form_log', session, NULL, substr(stamp,1,10) FROM form_log
  UNION ALL SELECT 'form_error_log', session, NULL, substr(stamp,1,10) FROM form_error_log
  UNION ALL SELECT 'read_log', session, NULL, substr(stamp,1,10) FROM read_log)
SELECT session, count(DISTINCT t) n_tables, group_concat(DISTINCT t) tables,
       group_concat(DISTINCT t || ':' || coalesce(user_id,'-')) users_by_table, group_concat(DISTINCT d) days
FROM s GROUP BY session HAVING count(DISTINCT t) > 1 ORDER BY n_tables DESC, session;
-- name: session_overlap_matrix
WITH s(t, session) AS (
  SELECT DISTINCT 'action_log', session FROM action_log
  UNION SELECT 'with_ip', session FROM action_log_with_ip
  UNION SELECT 'dup', session FROM dup_action_log
  UNION SELECT 'invalid', session FROM invalid_action_log
  UNION SELECT 'access_ok', session FROM access_log WHERE datetime(stamp) IS NOT NULL
  UNION SELECT 'access_shift', user_id FROM access_log WHERE datetime(stamp) IS NULL
  UNION SELECT 'activity', session FROM activity_log
  UNION SELECT 'form', session FROM form_log
  UNION SELECT 'form_error', session FROM form_error_log
  UNION SELECT 'read', session FROM read_log)
SELECT a.t, b.t t2, count(*) shared, (SELECT count(*) FROM s x WHERE x.t=a.t) n_a, (SELECT count(*) FROM s x WHERE x.t=b.t) n_b
FROM s a JOIN s b ON a.session=b.session AND a.t<b.t GROUP BY a.t, b.t ORDER BY shared DESC;
-- name: session_user_conflicts
-- sessions that map to more than one user across the user-bearing tables
WITH s(t, session, user_id) AS (
  SELECT 'action_log', session, user_id FROM action_log
  UNION ALL SELECT 'with_ip', session, user_id FROM action_log_with_ip
  UNION ALL SELECT 'dup', session, user_id FROM dup_action_log
  UNION ALL SELECT 'invalid', session, user_id FROM invalid_action_log
  UNION ALL SELECT 'access_ok', session, user_id FROM access_log WHERE datetime(stamp) IS NOT NULL)
SELECT session, group_concat(DISTINCT t||':'||user_id) mapping, count(DISTINCT user_id) n_users
FROM s GROUP BY session HAVING count(DISTINCT user_id) > 1 ORDER BY session;
-- name: user_ids_by_table
WITH u(t, user_id) AS (
  SELECT DISTINCT 'action_log', user_id FROM action_log UNION SELECT 'with_ip', user_id FROM action_log_with_ip
  UNION SELECT 'dup', user_id FROM dup_action_log UNION SELECT 'invalid', user_id FROM invalid_action_log
  UNION SELECT 'access_ok', user_id FROM access_log WHERE datetime(stamp) IS NOT NULL
  UNION SELECT 'purchase_log', user_id FROM purchase_log UNION SELECT 'app1', user_id FROM app1_mst_users
  UNION SELECT 'app2', user_id FROM app2_mst_users UNION SELECT 'card', user_id FROM mst_users_with_card_number)
SELECT t, count(*) n_users, group_concat(user_id) users,
       sum(user_id IN (SELECT user_id FROM mst_users)) in_mst_users FROM u GROUP BY t ORDER BY t;
-- name: invalid_vs_action_log
-- does each invalid_action_log row equal some action_log row except for the session id?
SELECT i.rowid, i.stamp, i.session, i.user_id, i.action, i.category, i.products, i.amount,
  (SELECT count(*) FROM action_log a WHERE a.user_id IS i.user_id AND a.action IS i.action AND a.category IS i.category
     AND a.products IS i.products AND a.amount IS i.amount AND a.stamp IS i.stamp) exact_but_session,
  (SELECT count(*) FROM action_log a WHERE a.user_id IS i.user_id AND a.action IS i.action AND a.category IS i.category
     AND a.amount IS i.amount AND (a.stamp IS i.stamp OR i.stamp IS NULL) AND (a.products IS i.products OR i.products IS NULL)) match_ignoring_nulled
FROM invalid_action_log i ORDER BY i.rowid;
-- name: with_ip_vs_others
-- action_log_with_ip rows matched in action_log / dup_action_log / access_log by (session,user,stamp) and by (user,stamp)
SELECT w.rowid, w.session, w.user_id, w.stamp, w.ip,
  (SELECT count(*) FROM action_log a WHERE a.session=w.session AND a.user_id=w.user_id AND a.stamp=w.stamp AND a.action=w.action) in_action_log,
  (SELECT count(*) FROM dup_action_log d WHERE d.session=w.session AND d.user_id=w.user_id AND d.stamp=w.stamp) dup_same_session,
  (SELECT count(*) FROM dup_action_log d WHERE d.user_id=w.user_id AND d.stamp=w.stamp) dup_user_stamp,
  (SELECT group_concat(d.session||'/'||d.user_id) FROM dup_action_log d WHERE d.stamp=w.stamp) dup_at_same_stamp
FROM action_log_with_ip w ORDER BY w.rowid;
-- name: ip_per_user
SELECT user_id, count(*) n, count(DISTINCT ip) n_ip, group_concat(DISTINCT ip) ips FROM action_log_with_ip GROUP BY user_id ORDER BY user_id;
-- name: dup_near_duplicates
-- pairs of rows in dup_action_log with the same session, user, action and product
SELECT a.rowid r1, b.rowid r2, a.session, a.user_id, a.action, a.products, a.stamp t1, b.stamp t2,
       (julianday(b.stamp)-julianday(a.stamp))*86400 AS gap_s
FROM dup_action_log a JOIN dup_action_log b ON a.session=b.session AND a.user_id=b.user_id AND a.action=b.action
  AND a.products=b.products AND a.rowid<b.rowid;
-- name: dup_same_user_product_any_session
SELECT a.rowid r1, b.rowid r2, a.user_id, a.products, a.session s1, b.session s2, a.stamp t1, b.stamp t2
FROM dup_action_log a JOIN dup_action_log b ON a.user_id=b.user_id AND a.products=b.products AND a.rowid<b.rowid;
-- name: products_snapshot_diff
-- 20161201 vs 20170101: kept / changed / deleted / added
SELECT coalesce(a.product_id,b.product_id) product_id, a.name n1, a.price p1, a.updated_at u1, b.name n2, b.price p2, b.updated_at u2,
  CASE WHEN b.product_id IS NULL THEN 'deleted' WHEN a.product_id IS NULL THEN 'added'
       WHEN a.name IS b.name AND a.price IS b.price AND a.updated_at IS b.updated_at THEN 'same' ELSE 'changed' END kind
FROM mst_products_20161201 a LEFT JOIN mst_products_20170101 b USING (product_id)
UNION ALL
SELECT b.product_id, NULL, NULL, NULL, b.name, b.price, b.updated_at, 'added'
FROM mst_products_20170101 b WHERE b.product_id NOT IN (SELECT product_id FROM mst_products_20161201)
ORDER BY 1;
-- name: products_updated_before_snapshot
SELECT 'mst_products_20161201' t, max(updated_at) mx, sum(updated_at >= '2016-12-01') at_or_after_cut FROM mst_products_20161201
UNION ALL SELECT 'mst_products_20170101', max(updated_at), sum(updated_at >= '2017-01-01') FROM mst_products_20170101;
-- name: product_ids_across_tables
WITH p(t, product_id) AS (
  SELECT 'mst_products_20161201', product_id FROM mst_products_20161201
  UNION SELECT 'mst_products_20170101', product_id FROM mst_products_20170101
  UNION SELECT 'product_sales', product_id FROM product_sales
  UNION SELECT 'dup_action_log', products FROM dup_action_log
  UNION SELECT 'invalid', products FROM invalid_action_log WHERE products IS NOT NULL
  UNION SELECT 'action_log', products FROM action_log WHERE products IS NOT NULL)
SELECT t, count(*) n_values, group_concat(product_id, ' ') vals FROM p GROUP BY t ORDER BY t;
-- name: categories_scd
SELECT id, count(*) n, group_concat(name||'@'||stamp, ' -> ') history FROM mst_categories GROUP BY id ORDER BY id;
-- name: category_names_across_tables
SELECT 'action_log' t, group_concat(DISTINCT category) v FROM action_log
UNION ALL SELECT 'product_sales', group_concat(DISTINCT category_name) FROM product_sales
UNION ALL SELECT 'mst_categories', group_concat(DISTINCT name) FROM mst_categories;
-- name: form_error_vs_form_log
SELECT count(DISTINCT e.session) err_sessions,
  (SELECT count(DISTINCT session) FROM form_log) form_sessions,
  (SELECT count(DISTINCT e2.session) FROM form_error_log e2 WHERE e2.session IN (SELECT session FROM form_log)) shared
FROM form_error_log e;
-- name: purchase_log_vs_action_log
SELECT p.*, (SELECT count(*) FROM action_log a WHERE a.user_id=p.user_id AND a.amount=p.amount) same_user_amount_in_action_log FROM purchase_log p;
