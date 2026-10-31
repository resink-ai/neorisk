-- Web and app logs: events → source tables (refdata rebuild, DuckDB). Logs are written back in
-- source rowid order, which the tie-dependent questions read.

-- table: mst_users
SELECT user_id, sex, birth_date, strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d') AS register_date,
       register_device, withdraw_date
FROM user_registered ORDER BY src_rowid;

-- table: action_log
SELECT session, user_id, action, category, products, amount,
       strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS stamp
FROM action_logged ORDER BY src_rowid;

-- table: activity_log
SELECT strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS stamp, session, action,
       option, path, search_type
FROM activity_logged ORDER BY src_rowid;

-- table: read_log
SELECT strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS stamp, session, action, url
FROM read_logged ORDER BY src_rowid;

-- table: form_log
SELECT strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS stamp, session, action,
       path, status
FROM form_viewed ORDER BY src_rowid;

-- table: form_error_log
SELECT strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS stamp, session, form, field,
       error_type, value
FROM form_error_logged ORDER BY src_rowid;

-- table: action_log_with_ip
SELECT session, user_id, action, ip,
       strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS stamp
FROM action_with_ip_logged ORDER BY src_rowid;

-- table: access_log
SELECT CASE WHEN shifted = 1 THEN strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S')
            ELSE session END AS session,
       user_id, action,
       CASE WHEN shifted = 1 THEN path_in_stamp
            ELSE strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') END AS stamp
FROM access_logged ORDER BY src_rowid;

-- table: action_log_with_noise
SELECT strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS stamp, session, action,
       products, url, ip, user_agent
FROM noisy_action_logged ORDER BY src_rowid;

-- table: invalid_action_log
SELECT CASE WHEN stamp_null = 1 THEN NULL
            ELSE strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') END AS stamp,
       session, user_id, action, category, products, amount
FROM invalid_action_logged ORDER BY src_rowid;

-- table: mst_categories
SELECT id, name, strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS stamp
FROM category_named ORDER BY src_rowid;

-- table: dup_action_log
SELECT strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS stamp, session, user_id,
       action, products
FROM dup_action_logged ORDER BY src_rowid;

-- table: mst_products_20161201
-- Each product's latest update before the cut, unless deleted after it and before the cut.
WITH u AS (SELECT *, row_number() OVER (PARTITION BY product_id ORDER BY event_time DESC, seq DESC)
                  AS k
           FROM product_updated WHERE event_time < TIMESTAMPTZ '2016-12-01 00:00:00+00')
SELECT product_id, name, price, strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S')
           AS updated_at
FROM u WHERE k = 1 AND NOT EXISTS (
    SELECT 1 FROM product_deleted d WHERE d.product_id = u.product_id
    AND d.event_time >= u.event_time AND d.event_time < TIMESTAMPTZ '2016-12-01 00:00:00+00');

-- table: mst_products_20170101
WITH u AS (SELECT *, row_number() OVER (PARTITION BY product_id ORDER BY event_time DESC, seq DESC)
                  AS k
           FROM product_updated WHERE event_time < TIMESTAMPTZ '2017-01-01 00:00:00+00')
SELECT product_id, name, price, strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S')
           AS updated_at
FROM u WHERE k = 1 AND NOT EXISTS (
    SELECT 1 FROM product_deleted d WHERE d.product_id = u.product_id
    AND d.event_time >= u.event_time AND d.event_time < TIMESTAMPTZ '2017-01-01 00:00:00+00');

-- table: app1_mst_users
SELECT ext_id AS user_id, name, email FROM app1_users;

-- table: app2_mst_users
SELECT ext_id AS user_id, name, phone FROM app2_users;

-- table: mst_users_with_card_number
SELECT ext_id AS user_id, card_number FROM user_cards;

-- table: purchase_log
SELECT purchase_id, user_id, amount,
       strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S') AS stamp
FROM purchase_logged ORDER BY src_rowid;

-- table: product_sales
SELECT category_name, ext_id AS product_id, sales FROM product_sales;
