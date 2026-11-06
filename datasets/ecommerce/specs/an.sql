-- Anchor modeling (6NF). An anchor per entity and per business event (identity and time),
-- one table per attribute, and one tie per relation (an_<e1>_<role>_<e2>). Static
-- attributes have no changed_at; the historized ones (a user's region, an order's return)
-- have one row per change. No nulls: an absent value is an absent row.
-- reservation_*, stock_restocked, checkout_failed and verification_failed are outside the
-- scope.

-- table: an_users
SELECT user_id, created_at FROM users;

-- table: an_users_age_band
SELECT user_id, age_band FROM users;

-- table: an_users_acquisition
SELECT user_id, acquisition FROM users;

-- table: an_users_region
WITH h AS (
    SELECT user_id, region, created_at AS ts, 0 AS ord FROM users
    UNION ALL
    SELECT user_id, region, event_time, seq FROM address_changed
), last AS (    -- two values at one instant: the later one (by seq) is the value at that time
    SELECT * FROM h
    QUALIFY row_number() OVER (PARTITION BY user_id, ts ORDER BY ord DESC) = 1
)
SELECT user_id, region, ts AS changed_at
FROM last
QUALIFY lag(region) OVER (PARTITION BY user_id ORDER BY ts) IS DISTINCT FROM region;

-- table: an_users_invitedby_users
SELECT user_id, invited_by AS inviter_id FROM users WHERE invited_by IS NOT NULL;

-- table: an_devices
SELECT device_id, created_at FROM devices;

-- table: an_devices_os
SELECT device_id, os FROM devices;

-- table: an_devices_kind
SELECT device_id, kind FROM devices;

-- table: an_devices_ownedby_users
SELECT device_id, user_id FROM devices;

-- table: an_skus
SELECT sku_id, created_at FROM skus;

-- table: an_skus_category
SELECT sku_id, category FROM skus;

-- table: an_skus_price
SELECT sku_id, price FROM skus;

-- table: an_orders
SELECT order_id, event_time AS placed_at FROM order_placed;

-- table: an_orders_amount
SELECT order_id, amount FROM orders;

-- table: an_orders_lines
SELECT order_id, lines FROM orders;

-- table: an_orders_return_amount
SELECT order_id, amount AS return_amount, event_time AS changed_at FROM order_returned;

-- table: an_orders_placedby_users
SELECT order_id, user_id FROM order_placed;

-- table: an_orders_placedon_devices
SELECT order_id, device_id FROM order_placed;

-- table: an_order_lines
SELECT line_id, created_at FROM order_lines;

-- table: an_order_lines_quantity
SELECT line_id, quantity FROM order_lines;

-- table: an_order_lines_amount
SELECT line_id, amount FROM order_lines;

-- table: an_order_lines_partof_orders
SELECT line_id, order_id FROM order_lines;

-- table: an_order_lines_for_skus
SELECT line_id, sku_id FROM order_lines;

-- table: an_sessions
SELECT session_id, event_time AS started_at FROM session_started;

-- table: an_sessions_by_users
SELECT session_id, user_id FROM session_started;

-- table: an_sessions_on_devices
SELECT session_id, device_id FROM session_started;

-- table: an_product_views
SELECT event_id AS view_id, event_time AS viewed_at FROM product_viewed;

-- table: an_product_views_in_sessions
SELECT event_id AS view_id, session_id FROM product_viewed;

-- table: an_product_views_of_skus
SELECT event_id AS view_id, sku_id FROM product_viewed;

-- table: an_referral_bonus
SELECT event_id AS bonus_id, event_time AS decided_at FROM referral_bonus_paid
UNION ALL
SELECT event_id, event_time FROM referral_bonus_rejected;

-- table: an_referral_bonus_outcome
SELECT event_id AS bonus_id, 'paid' AS outcome FROM referral_bonus_paid
UNION ALL
SELECT event_id, 'rejected' FROM referral_bonus_rejected;

-- table: an_referral_bonus_amount
SELECT event_id AS bonus_id, amount FROM referral_bonus_paid;

-- table: an_referral_bonus_to_users
SELECT event_id AS bonus_id, user_id AS inviter_id FROM referral_bonus_paid
UNION ALL
SELECT event_id, user_id FROM referral_bonus_rejected;

-- table: an_referral_bonus_for_users
SELECT event_id AS bonus_id, invitee_id FROM referral_bonus_paid
UNION ALL
SELECT event_id, invitee_id FROM referral_bonus_rejected;
