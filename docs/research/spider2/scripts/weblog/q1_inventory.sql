-- Inventory: counts, distinct rows, candidate keys, nulls/empties, time text shapes.
-- name: rows_and_distinct
SELECT 'access_log' t, (SELECT count(*) FROM access_log) n, (SELECT count(*) FROM (SELECT DISTINCT * FROM access_log)) n_distinct
UNION ALL SELECT 'action_log', (SELECT count(*) FROM action_log), (SELECT count(*) FROM (SELECT DISTINCT * FROM action_log))
UNION ALL SELECT 'action_log_with_ip', (SELECT count(*) FROM action_log_with_ip), (SELECT count(*) FROM (SELECT DISTINCT * FROM action_log_with_ip))
UNION ALL SELECT 'action_log_with_noise', (SELECT count(*) FROM action_log_with_noise), (SELECT count(*) FROM (SELECT DISTINCT * FROM action_log_with_noise))
UNION ALL SELECT 'activity_log', (SELECT count(*) FROM activity_log), (SELECT count(*) FROM (SELECT DISTINCT * FROM activity_log))
UNION ALL SELECT 'app1_mst_users', (SELECT count(*) FROM app1_mst_users), (SELECT count(*) FROM (SELECT DISTINCT * FROM app1_mst_users))
UNION ALL SELECT 'app2_mst_users', (SELECT count(*) FROM app2_mst_users), (SELECT count(*) FROM (SELECT DISTINCT * FROM app2_mst_users))
UNION ALL SELECT 'dup_action_log', (SELECT count(*) FROM dup_action_log), (SELECT count(*) FROM (SELECT DISTINCT * FROM dup_action_log))
UNION ALL SELECT 'form_error_log', (SELECT count(*) FROM form_error_log), (SELECT count(*) FROM (SELECT DISTINCT * FROM form_error_log))
UNION ALL SELECT 'form_log', (SELECT count(*) FROM form_log), (SELECT count(*) FROM (SELECT DISTINCT * FROM form_log))
UNION ALL SELECT 'invalid_action_log', (SELECT count(*) FROM invalid_action_log), (SELECT count(*) FROM (SELECT DISTINCT * FROM invalid_action_log))
UNION ALL SELECT 'mst_categories', (SELECT count(*) FROM mst_categories), (SELECT count(*) FROM (SELECT DISTINCT * FROM mst_categories))
UNION ALL SELECT 'mst_products_20161201', (SELECT count(*) FROM mst_products_20161201), (SELECT count(*) FROM (SELECT DISTINCT * FROM mst_products_20161201))
UNION ALL SELECT 'mst_products_20170101', (SELECT count(*) FROM mst_products_20170101), (SELECT count(*) FROM (SELECT DISTINCT * FROM mst_products_20170101))
UNION ALL SELECT 'mst_users', (SELECT count(*) FROM mst_users), (SELECT count(*) FROM (SELECT DISTINCT * FROM mst_users))
UNION ALL SELECT 'mst_users_with_card_number', (SELECT count(*) FROM mst_users_with_card_number), (SELECT count(*) FROM (SELECT DISTINCT * FROM mst_users_with_card_number))
UNION ALL SELECT 'product_sales', (SELECT count(*) FROM product_sales), (SELECT count(*) FROM (SELECT DISTINCT * FROM product_sales))
UNION ALL SELECT 'purchase_log', (SELECT count(*) FROM purchase_log), (SELECT count(*) FROM (SELECT DISTINCT * FROM purchase_log))
UNION ALL SELECT 'read_log', (SELECT count(*) FROM read_log), (SELECT count(*) FROM (SELECT DISTINCT * FROM read_log));
-- name: total_rows
SELECT (SELECT count(*) FROM access_log)+(SELECT count(*) FROM action_log)+(SELECT count(*) FROM action_log_with_ip)
 +(SELECT count(*) FROM activity_log)+(SELECT count(*) FROM app1_mst_users)+(SELECT count(*) FROM app2_mst_users)
 +(SELECT count(*) FROM dup_action_log)+(SELECT count(*) FROM form_error_log)+(SELECT count(*) FROM form_log)
 +(SELECT count(*) FROM invalid_action_log)+(SELECT count(*) FROM mst_categories)+(SELECT count(*) FROM mst_products_20161201)
 +(SELECT count(*) FROM mst_products_20170101)+(SELECT count(*) FROM mst_users)+(SELECT count(*) FROM mst_users_with_card_number)
 +(SELECT count(*) FROM product_sales)+(SELECT count(*) FROM purchase_log)+(SELECT count(*) FROM read_log) AS total;
-- name: candidate_keys
SELECT 'purchase_log.purchase_id' k, count(*) n, count(DISTINCT purchase_id) d FROM purchase_log
UNION ALL SELECT 'mst_users.user_id', count(*), count(DISTINCT user_id) FROM mst_users
UNION ALL SELECT 'mst_categories.id', count(*), count(DISTINCT id) FROM mst_categories
UNION ALL SELECT 'mst_categories.(id,stamp)', count(*), count(DISTINCT id||'|'||stamp) FROM mst_categories
UNION ALL SELECT 'mst_products_20161201.product_id', count(*), count(DISTINCT product_id) FROM mst_products_20161201
UNION ALL SELECT 'mst_products_20170101.product_id', count(*), count(DISTINCT product_id) FROM mst_products_20170101
UNION ALL SELECT 'product_sales.product_id', count(*), count(DISTINCT product_id) FROM product_sales
UNION ALL SELECT 'app1_mst_users.user_id', count(*), count(DISTINCT user_id) FROM app1_mst_users
UNION ALL SELECT 'app2_mst_users.user_id', count(*), count(DISTINCT user_id) FROM app2_mst_users
UNION ALL SELECT 'card.user_id', count(*), count(DISTINCT user_id) FROM mst_users_with_card_number
UNION ALL SELECT 'read_log.(session,action)', count(*), count(DISTINCT session||'|'||action) FROM read_log
UNION ALL SELECT 'form_error_log.(session,stamp,field)', count(*), count(DISTINCT session||'|'||stamp||'|'||field) FROM form_error_log
UNION ALL SELECT 'dup_action_log.(session,stamp)', count(*), count(DISTINCT session||'|'||stamp) FROM dup_action_log
UNION ALL SELECT 'action_log_with_ip.session', count(*), count(DISTINCT session) FROM action_log_with_ip;
-- name: mst_users_versions_per_user
-- distinct full rows per user and copies per user
SELECT user_id, count(*) n_rows, count(DISTINCT sex||birth_date||register_date||register_device||coalesce(withdraw_date,'<null>')) n_versions,
       group_concat(DISTINCT register_date) register_dates
FROM mst_users GROUP BY user_id ORDER BY user_id;
-- name: null_and_empty_counts
SELECT 'action_log.category' c, sum(category IS NULL) nulls, sum(category='') empties FROM action_log
UNION ALL SELECT 'action_log.products', sum(products IS NULL), sum(products='') FROM action_log
UNION ALL SELECT 'action_log.amount', sum(amount IS NULL), 0 FROM action_log
UNION ALL SELECT 'activity_log.path', sum(path IS NULL), sum(path='') FROM activity_log
UNION ALL SELECT 'activity_log.search_type', sum(search_type IS NULL), sum(search_type='') FROM activity_log
UNION ALL SELECT 'form_log.status', sum(status IS NULL), sum(status='') FROM form_log
UNION ALL SELECT 'form_error_log.value', sum(value IS NULL), sum(value='') FROM form_error_log
UNION ALL SELECT 'invalid_action_log.stamp', sum(stamp IS NULL), sum(stamp='') FROM invalid_action_log
UNION ALL SELECT 'invalid_action_log.category', sum(category IS NULL), sum(category='') FROM invalid_action_log
UNION ALL SELECT 'invalid_action_log.products', sum(products IS NULL), sum(products='') FROM invalid_action_log
UNION ALL SELECT 'invalid_action_log.amount', sum(amount IS NULL), 0 FROM invalid_action_log
UNION ALL SELECT 'mst_users.withdraw_date', sum(withdraw_date IS NULL), sum(withdraw_date='') FROM mst_users
UNION ALL SELECT 'card.card_number', sum(card_number IS NULL), sum(card_number='') FROM mst_users_with_card_number;
-- name: backslash_N_anywhere
-- any '\N' text or leading/trailing whitespace in any text cell of any table
WITH cells(t, v) AS (
  SELECT 'access_log', session FROM access_log UNION ALL SELECT 'access_log', user_id FROM access_log
  UNION ALL SELECT 'access_log', action FROM access_log UNION ALL SELECT 'access_log', stamp FROM access_log
  UNION ALL SELECT 'action_log', session FROM action_log UNION ALL SELECT 'action_log', category FROM action_log
  UNION ALL SELECT 'action_log', products FROM action_log UNION ALL SELECT 'action_log', stamp FROM action_log
  UNION ALL SELECT 'activity_log', path FROM activity_log UNION ALL SELECT 'activity_log', search_type FROM activity_log
  UNION ALL SELECT 'activity_log', option FROM activity_log UNION ALL SELECT 'activity_log', stamp FROM activity_log
  UNION ALL SELECT 'form_log', path FROM form_log UNION ALL SELECT 'form_log', status FROM form_log
  UNION ALL SELECT 'form_error_log', value FROM form_error_log UNION ALL SELECT 'read_log', url FROM read_log
  UNION ALL SELECT 'read_log', action FROM read_log UNION ALL SELECT 'mst_users', withdraw_date FROM mst_users
  UNION ALL SELECT 'mst_users', birth_date FROM mst_users UNION ALL SELECT 'mst_users', register_date FROM mst_users
  UNION ALL SELECT 'product_sales', category_name FROM product_sales UNION ALL SELECT 'app1', email FROM app1_mst_users
  UNION ALL SELECT 'app2', phone FROM app2_mst_users UNION ALL SELECT 'card', card_number FROM mst_users_with_card_number
  UNION ALL SELECT 'invalid', stamp FROM invalid_action_log UNION ALL SELECT 'invalid', products FROM invalid_action_log
  UNION ALL SELECT 'dup', stamp FROM dup_action_log UNION ALL SELECT 'ip', ip FROM action_log_with_ip
  UNION ALL SELECT 'mst_categories', stamp FROM mst_categories UNION ALL SELECT 'mst_products_20161201', updated_at FROM mst_products_20161201
  UNION ALL SELECT 'mst_products_20170101', updated_at FROM mst_products_20170101 UNION ALL SELECT 'purchase_log', stamp FROM purchase_log)
SELECT t, sum(v = '\N') backslash_n, sum(v <> trim(v)) untrimmed, sum(v GLOB '*[^ -~]*') non_ascii, count(v) non_null FROM cells GROUP BY t ORDER BY t;
-- name: time_shapes
-- per time column: how many values match 'YYYY-MM-DD HH:MM:SS', 'YYYY-MM-DD', other, NULL; min, max
WITH s(t, v) AS (
  SELECT 'access_log.stamp', stamp FROM access_log UNION ALL SELECT 'access_log.session', session FROM access_log
  UNION ALL SELECT 'action_log.stamp', stamp FROM action_log UNION ALL SELECT 'action_log_with_ip.stamp', stamp FROM action_log_with_ip
  UNION ALL SELECT 'activity_log.stamp', stamp FROM activity_log UNION ALL SELECT 'dup_action_log.stamp', stamp FROM dup_action_log
  UNION ALL SELECT 'form_error_log.stamp', stamp FROM form_error_log UNION ALL SELECT 'form_log.stamp', stamp FROM form_log
  UNION ALL SELECT 'invalid_action_log.stamp', stamp FROM invalid_action_log UNION ALL SELECT 'mst_categories.stamp', stamp FROM mst_categories
  UNION ALL SELECT 'mst_products_20161201.updated_at', updated_at FROM mst_products_20161201
  UNION ALL SELECT 'mst_products_20170101.updated_at', updated_at FROM mst_products_20170101
  UNION ALL SELECT 'mst_users.birth_date', birth_date FROM mst_users UNION ALL SELECT 'mst_users.register_date', register_date FROM mst_users
  UNION ALL SELECT 'mst_users.withdraw_date', withdraw_date FROM mst_users UNION ALL SELECT 'purchase_log.stamp', stamp FROM purchase_log
  UNION ALL SELECT 'read_log.stamp', stamp FROM read_log)
SELECT t,
  sum(v GLOB '[12][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9] [0-2][0-9]:[0-5][0-9]:[0-5][0-9]' AND length(v)=19 AND datetime(v) = v) iso_sec,
  sum(v GLOB '[12][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]' AND length(v)=10 AND date(v) = v) iso_date,
  sum(v IS NOT NULL AND datetime(v) IS NULL) other, sum(v IS NULL) nulls,
  min(CASE WHEN datetime(v) IS NOT NULL THEN v END) mn, max(CASE WHEN datetime(v) IS NOT NULL THEN v END) mx,
  sum(substr(v,18,2) <> '00' AND length(v)=19) nonzero_seconds
FROM s GROUP BY t ORDER BY t;
-- name: access_log_shift
-- rows whose stamp is not a time: where is the time? (column-shift check)
SELECT rowid, session AS stamp_like, user_id AS session_like, action AS user_like, stamp AS path_like,
       datetime(session) IS NOT NULL AS session_is_time, length(user_id) len_user_col
FROM access_log WHERE datetime(stamp) IS NULL ORDER BY rowid;
-- name: access_log_shift_summary
SELECT datetime(stamp) IS NOT NULL AS stamp_ok, count(*) n, sum(datetime(session) IS NOT NULL) session_is_time,
       group_concat(DISTINCT action) actions, min(rowid) r0, max(rowid) r1
FROM access_log GROUP BY 1;
-- name: global_time_range
WITH s(v) AS (SELECT stamp FROM access_log UNION ALL SELECT session FROM access_log UNION ALL SELECT stamp FROM action_log
  UNION ALL SELECT stamp FROM action_log_with_ip UNION ALL SELECT stamp FROM activity_log UNION ALL SELECT stamp FROM dup_action_log
  UNION ALL SELECT stamp FROM form_error_log UNION ALL SELECT stamp FROM form_log UNION ALL SELECT stamp FROM invalid_action_log
  UNION ALL SELECT stamp FROM mst_categories UNION ALL SELECT updated_at FROM mst_products_20161201
  UNION ALL SELECT updated_at FROM mst_products_20170101 UNION ALL SELECT register_date FROM mst_users
  UNION ALL SELECT withdraw_date FROM mst_users UNION ALL SELECT stamp FROM purchase_log UNION ALL SELECT stamp FROM read_log)
SELECT min(datetime(v)) first_time, max(datetime(v)) last_time FROM s WHERE datetime(v) IS NOT NULL;
