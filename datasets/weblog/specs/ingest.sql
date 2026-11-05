-- Web and app logs: source tables → events (refdata ingest). Every log keeps its rowid as ord.
-- Snapshots at N = 2017-03-02 10:00:00, the latest time in the file (purchase_log).

-- entity: app1_users
SELECT user_id AS ext_id, name, '2016-01-01 00:00:00' AS created_at
FROM app1_mst_users ORDER BY user_id;

-- entity: app2_users
SELECT user_id AS ext_id, name, '2016-01-01 00:00:00' AS created_at
FROM app2_mst_users ORDER BY user_id;

-- entity: user_cards
SELECT user_id AS ext_id, '2016-01-01 00:00:00' AS created_at
FROM mst_users_with_card_number ORDER BY user_id;

-- entity: product_sales
SELECT product_id AS ext_id, category_name, '2016-01-01 00:00:00' AS created_at
FROM product_sales ORDER BY product_id;

-- event: access_logged owner=user_id ord=src_rowid
-- Shifted rows hold the time in `session` and a path in `stamp`.
SELECT CASE WHEN datetime(stamp) IS NULL THEN session ELSE stamp END AS event_time, user_id,
       CASE WHEN datetime(stamp) IS NULL THEN NULL ELSE session END AS session, action,
       datetime(stamp) IS NULL AS shifted,
       CASE WHEN datetime(stamp) IS NULL THEN stamp END AS path_in_stamp, rowid AS src_rowid
FROM access_log ORDER BY rowid;

-- event: action_logged owner=session ord=src_rowid
SELECT stamp AS event_time, session, user_id, action, category, products, amount,
       rowid AS src_rowid
FROM action_log ORDER BY rowid;

-- event: action_with_ip_logged owner=session ord=src_rowid
SELECT stamp AS event_time, session, user_id, action, ip, rowid AS src_rowid
FROM action_log_with_ip ORDER BY rowid;

-- event: noisy_action_logged owner=session ord=src_rowid
SELECT stamp AS event_time, session, action, products, url, ip, user_agent, rowid AS src_rowid
FROM action_log_with_noise ORDER BY rowid;

-- event: dup_action_logged owner=session ord=src_rowid
SELECT stamp AS event_time, session, user_id, action, products, rowid AS src_rowid
FROM dup_action_log ORDER BY rowid;

-- event: invalid_action_logged owner=session ord=src_rowid
-- A NULL stamp takes the latest stamp of an earlier row in its session (a rule).
SELECT coalesce(stamp, (SELECT max(b.stamp) FROM invalid_action_log b
                        WHERE b.session = a.session AND b.rowid < a.rowid)) AS event_time,
       stamp IS NULL AS stamp_null, session, user_id, action, category, products, amount,
       rowid AS src_rowid
FROM invalid_action_log a ORDER BY rowid;

-- event: activity_logged owner=session ord=src_rowid
SELECT stamp AS event_time, session, action, option, path, search_type, rowid AS src_rowid
FROM activity_log ORDER BY rowid;

-- event: read_logged owner=session ord=src_rowid
SELECT stamp AS event_time, session, action, url, rowid AS src_rowid FROM read_log ORDER BY rowid;

-- event: form_viewed owner=session ord=src_rowid
SELECT stamp AS event_time, session, action, path, status, rowid AS src_rowid
FROM form_log ORDER BY rowid;

-- event: form_error_logged owner=session ord=src_rowid
SELECT stamp AS event_time, session, form, field, error_type, value, rowid AS src_rowid
FROM form_error_log ORDER BY rowid;

-- event: purchase_logged owner=user_id ord=src_rowid
SELECT stamp AS event_time, user_id, purchase_id, amount, rowid AS src_rowid
FROM purchase_log ORDER BY rowid;

-- event: user_registered owner=user_id ord=src_rowid
SELECT register_date || ' 00:00:00' AS event_time, user_id, sex, birth_date, register_device,
       withdraw_date, rowid AS src_rowid
FROM mst_users ORDER BY rowid;

-- event: category_named owner=id ord=src_rowid
SELECT stamp AS event_time, id, name, rowid AS src_rowid FROM mst_categories ORDER BY rowid;

-- event: product_updated owner=product_id
-- The first snapshot's rows, then the second's rows that differ from the first.
SELECT updated_at AS event_time, product_id, name, price
FROM (SELECT * FROM mst_products_20161201
      UNION
      SELECT n.* FROM mst_products_20170101 n LEFT JOIN mst_products_20161201 o
          ON o.product_id = n.product_id AND o.name IS n.name AND o.price IS n.price
             AND o.updated_at IS n.updated_at
      WHERE o.product_id IS NULL)
ORDER BY updated_at, product_id;

-- event: product_deleted owner=product_id
-- In the first snapshot, gone from the second: deleted at the first cut (a rule).
SELECT '2016-12-01 00:00:00' AS event_time, product_id
FROM mst_products_20161201
WHERE product_id NOT IN (SELECT product_id FROM mst_products_20170101) ORDER BY product_id;

-- event: app1_users_snapshot owner=app1_users_key
SELECT '2017-03-02 10:00:00' AS event_time, user_id AS app1_users_key, email
FROM app1_mst_users ORDER BY user_id;

-- event: app2_users_snapshot owner=app2_users_key
SELECT '2017-03-02 10:00:00' AS event_time, user_id AS app2_users_key, phone
FROM app2_mst_users ORDER BY user_id;

-- event: user_cards_snapshot owner=user_card_key
SELECT '2017-03-02 10:00:00' AS event_time, user_id AS user_card_key, card_number
FROM mst_users_with_card_number ORDER BY user_id;

-- event: product_sales_snapshot owner=product_sales_key
SELECT '2017-03-02 10:00:00' AS event_time, product_id AS product_sales_key, sales
FROM product_sales ORDER BY product_id;
