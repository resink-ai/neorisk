-- Data Vault 2.0. Hash keys are md5 of the business key as text; link keys md5 of the parent
-- hash keys (and a dependent child key) joined by '||'; hashdiff is md5 of the attributes
-- joined by '||' with nulls as ''. Insert-only: load_dts is the event time, record_source
-- the log event type. A user's region has its own satellite, one row per change.
-- reservation_*, stock_restocked, checkout_failed and verification_failed are outside the
-- scope.

-- table: dv_hub_users
SELECT md5(CAST(user_id AS VARCHAR)) AS user_hk, user_id, created_at AS load_dts,
       'users_created' AS record_source
FROM users;

-- table: dv_hub_devices
SELECT md5(CAST(device_id AS VARCHAR)) AS device_hk, device_id, created_at AS load_dts,
       'devices_created' AS record_source
FROM devices;

-- table: dv_hub_skus
SELECT md5(CAST(sku_id AS VARCHAR)) AS sku_hk, sku_id, created_at AS load_dts,
       'skus_created' AS record_source
FROM skus;

-- table: dv_hub_orders
SELECT md5(CAST(order_id AS VARCHAR)) AS order_hk, order_id, created_at AS load_dts,
       'orders_created' AS record_source
FROM orders;

-- table: dv_hub_sessions
SELECT md5(CAST(session_id AS VARCHAR)) AS session_hk, session_id, event_time AS load_dts,
       'session_started' AS record_source
FROM session_started;

-- table: dv_link_device_user
WITH k AS (SELECT md5(CAST(device_id AS VARCHAR)) AS device_hk,
                  md5(CAST(user_id AS VARCHAR)) AS user_hk, created_at FROM devices)
SELECT md5(device_hk || '||' || user_hk) AS device_user_hk, device_hk, user_hk,
       created_at AS load_dts, 'devices_created' AS record_source
FROM k;

-- table: dv_link_user_inviter
WITH k AS (SELECT md5(CAST(user_id AS VARCHAR)) AS user_hk,
                  md5(CAST(invited_by AS VARCHAR)) AS inviter_hk, created_at
           FROM users WHERE invited_by IS NOT NULL)
SELECT md5(user_hk || '||' || inviter_hk) AS user_inviter_hk, user_hk, inviter_hk,
       created_at AS load_dts, 'users_created' AS record_source
FROM k;

-- table: dv_link_order
WITH k AS (SELECT md5(CAST(order_id AS VARCHAR)) AS order_hk,
                  md5(CAST(user_id AS VARCHAR)) AS user_hk,
                  md5(CAST(device_id AS VARCHAR)) AS device_hk, event_time
           FROM order_placed)
SELECT md5(order_hk || '||' || user_hk || '||' || device_hk) AS order_link_hk,
       order_hk, user_hk, device_hk, event_time AS load_dts, 'order_placed' AS record_source
FROM k;

-- table: dv_link_order_line
WITH k AS (SELECT md5(CAST(order_id AS VARCHAR)) AS order_hk,
                  md5(CAST(sku_id AS VARCHAR)) AS sku_hk, line_id, created_at
           FROM order_lines)
SELECT md5(order_hk || '||' || sku_hk || '||' || CAST(line_id AS VARCHAR)) AS order_line_hk,
       order_hk, sku_hk, line_id, created_at AS load_dts,
       'order_lines_created' AS record_source
FROM k;

-- table: dv_link_session
WITH k AS (SELECT md5(CAST(session_id AS VARCHAR)) AS session_hk,
                  md5(CAST(user_id AS VARCHAR)) AS user_hk,
                  md5(CAST(device_id AS VARCHAR)) AS device_hk, event_time
           FROM session_started)
SELECT md5(session_hk || '||' || user_hk || '||' || device_hk) AS session_link_hk,
       session_hk, user_hk, device_hk, event_time AS load_dts,
       'session_started' AS record_source
FROM k;

-- table: dv_link_product_view
WITH k AS (SELECT md5(CAST(session_id AS VARCHAR)) AS session_hk,
                  md5(CAST(sku_id AS VARCHAR)) AS sku_hk, event_id, event_time
           FROM product_viewed)
SELECT md5(session_hk || '||' || sku_hk || '||' || CAST(event_id AS VARCHAR))
           AS product_view_hk,
       session_hk, sku_hk, event_id AS view_id, event_time AS load_dts,
       'product_viewed' AS record_source
FROM k;

-- table: dv_link_referral_bonus
WITH b AS (
    SELECT user_id, invitee_id, event_time, seq, event_type FROM referral_bonus_paid
    UNION ALL
    SELECT user_id, invitee_id, event_time, seq, event_type FROM referral_bonus_rejected
), k AS (
    SELECT md5(CAST(user_id AS VARCHAR)) AS inviter_hk,
           md5(CAST(invitee_id AS VARCHAR)) AS invitee_hk, event_time, seq, event_type
    FROM b
)
SELECT md5(inviter_hk || '||' || invitee_hk) AS referral_bonus_hk, inviter_hk, invitee_hk,
       event_time AS load_dts, event_type AS record_source
FROM k
QUALIFY row_number() OVER (PARTITION BY inviter_hk, invitee_hk ORDER BY seq) = 1;

-- table: dv_sat_users_profile
SELECT md5(CAST(user_id AS VARCHAR)) AS user_hk, created_at AS load_dts,
       'users_created' AS record_source,
       md5(coalesce(age_band, '') || '||' || coalesce(acquisition, '')) AS hashdiff,
       age_band, acquisition
FROM users;

-- table: dv_sat_users_region
WITH h AS (
    SELECT user_id, region, created_at AS ts, 0 AS ord, 'users_created' AS src FROM users
    UNION ALL
    SELECT user_id, region, event_time, seq, 'address_changed' FROM address_changed
), last AS (    -- two values at one instant: the later one (by seq) is the value at that time
    SELECT * FROM h
    QUALIFY row_number() OVER (PARTITION BY user_id, ts ORDER BY ord DESC) = 1
), d AS (
    SELECT *, md5(coalesce(region, '')) AS hashdiff FROM last
)
SELECT md5(CAST(user_id AS VARCHAR)) AS user_hk, ts AS load_dts, src AS record_source,
       hashdiff, region
FROM d
QUALIFY lag(hashdiff) OVER (PARTITION BY user_id ORDER BY ts) IS DISTINCT FROM hashdiff;

-- table: dv_sat_devices_details
SELECT md5(CAST(device_id AS VARCHAR)) AS device_hk, created_at AS load_dts,
       'devices_created' AS record_source,
       md5(coalesce(os, '') || '||' || coalesce(kind, '')) AS hashdiff, os, kind
FROM devices;

-- table: dv_sat_skus_details
SELECT md5(CAST(sku_id AS VARCHAR)) AS sku_hk, created_at AS load_dts,
       'skus_created' AS record_source,
       md5(coalesce(category, '') || '||' || coalesce(CAST(price AS VARCHAR), '')) AS hashdiff,
       category, price
FROM skus;

-- table: dv_sat_orders_details
SELECT md5(CAST(order_id AS VARCHAR)) AS order_hk, created_at AS load_dts,
       'orders_created' AS record_source,
       md5(coalesce(CAST(lines AS VARCHAR), '') || '||' || coalesce(CAST(amount AS VARCHAR), ''))
           AS hashdiff,
       lines, amount
FROM orders;

-- table: dv_sat_order_line_details
SELECT md5(md5(CAST(order_id AS VARCHAR)) || '||' || md5(CAST(sku_id AS VARCHAR)) || '||'
           || CAST(line_id AS VARCHAR)) AS order_line_hk,
       created_at AS load_dts, 'order_lines_created' AS record_source,
       md5(coalesce(CAST(quantity AS VARCHAR), '') || '||' || coalesce(CAST(amount AS VARCHAR), ''))
           AS hashdiff,
       quantity, amount
FROM order_lines;

-- table: dv_sat_orders_return
SELECT md5(CAST(order_id AS VARCHAR)) AS order_hk, event_time AS load_dts,
       'order_returned' AS record_source, md5(coalesce(CAST(amount AS VARCHAR), '')) AS hashdiff,
       amount AS return_amount
FROM order_returned;

-- table: dv_sat_referral_bonus_outcome
WITH b AS (
    SELECT user_id, invitee_id, event_time, seq, event_type, 'paid' AS outcome, amount
    FROM referral_bonus_paid
    UNION ALL
    SELECT user_id, invitee_id, event_time, seq, event_type, 'rejected', CAST(NULL AS BIGINT)
    FROM referral_bonus_rejected
), d AS (
    SELECT md5(md5(CAST(user_id AS VARCHAR)) || '||' || md5(CAST(invitee_id AS VARCHAR)))
               AS referral_bonus_hk,
           event_time AS load_dts, seq, event_type AS record_source,
           md5(outcome || '||' || coalesce(CAST(amount AS VARCHAR), '')) AS hashdiff,
           outcome, amount
    FROM b
)
SELECT referral_bonus_hk, load_dts, record_source, hashdiff, outcome, amount
FROM d
QUALIFY lag(hashdiff) OVER (PARTITION BY referral_bonus_hk ORDER BY load_dts, seq)
        IS DISTINCT FROM hashdiff;
