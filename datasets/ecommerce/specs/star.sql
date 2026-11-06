-- Star schema (Kimball). Users are SCD2 on region (from address_changed); every other
-- dimension is static. Each fact row carries the users_sk in force at its event time
-- (valid_from <= t < valid_to). reservation_*, stock_restocked, checkout_failed and
-- verification_failed are outside the scope.

-- table: star_dim_users
WITH h AS (
    SELECT user_id, region, created_at AS ts, 0 AS ord FROM users
    UNION ALL
    SELECT user_id, region, event_time, seq FROM address_changed
)
SELECT row_number() OVER (ORDER BY h.user_id, h.ts, h.ord) AS users_sk,
       h.user_id, u.age_band, h.region, u.acquisition, u.invited_by,
       h.ts AS valid_from,
       lead(h.ts) OVER (PARTITION BY h.user_id ORDER BY h.ts, h.ord) AS valid_to,
       lead(h.ts) OVER (PARTITION BY h.user_id ORDER BY h.ts, h.ord) IS NULL AS is_current
FROM h JOIN users u USING (user_id);

-- table: star_dim_devices
SELECT device_id, user_id, os, kind, created_at FROM devices;

-- table: star_dim_skus
SELECT sku_id, category, price, created_at FROM skus;

-- table: star_fact_orders
SELECT p.order_id, d.users_sk, p.user_id, p.device_id, p.sku_id AS first_sku_id,
       p.quantity AS first_quantity, o.lines, p.amount, p.event_time AS ordered_at
FROM order_placed p
JOIN orders o USING (order_id)
JOIN star_dim_users d ON d.user_id = p.user_id AND d.valid_from <= p.event_time
 AND (d.valid_to IS NULL OR p.event_time < d.valid_to);

-- table: star_fact_order_lines
SELECT l.line_id, l.order_id, f.users_sk, f.user_id, l.sku_id, l.quantity, l.amount,
       l.created_at AS ordered_at
FROM order_lines l JOIN star_fact_orders f USING (order_id);

-- table: star_fact_sessions
SELECT s.session_id, d.users_sk, s.user_id, s.device_id, s.event_time AS started_at
FROM session_started s
JOIN star_dim_users d ON d.user_id = s.user_id AND d.valid_from <= s.event_time
 AND (d.valid_to IS NULL OR s.event_time < d.valid_to);

-- table: star_fact_product_views
SELECT v.event_id AS view_id, v.session_id, d.users_sk, v.user_id, v.device_id, v.sku_id,
       v.event_time AS viewed_at
FROM product_viewed v
JOIN star_dim_users d ON d.user_id = v.user_id AND d.valid_from <= v.event_time
 AND (d.valid_to IS NULL OR v.event_time < d.valid_to);

-- table: star_fact_returns
SELECT r.event_id AS return_id, r.order_id, d.users_sk, r.user_id, r.amount,
       r.event_time AS returned_at
FROM order_returned r
JOIN star_dim_users d ON d.user_id = r.user_id AND d.valid_from <= r.event_time
 AND (d.valid_to IS NULL OR r.event_time < d.valid_to);

-- table: star_fact_referral_bonus
WITH b AS (
    SELECT event_id, event_time, user_id, invitee_id, 'paid' AS outcome, amount
    FROM referral_bonus_paid
    UNION ALL
    SELECT event_id, event_time, user_id, invitee_id, 'rejected', CAST(NULL AS BIGINT)
    FROM referral_bonus_rejected
)
-- The pack can pick an inviter whose account is created after the invitee's bonus; such a
-- bonus points at the inviter's first version.
, first AS (SELECT user_id, min(users_sk) AS users_sk FROM star_dim_users GROUP BY user_id)
SELECT b.event_id AS bonus_id, di.users_sk AS inviter_sk, b.user_id AS inviter_id,
       de.users_sk AS invitee_sk, b.invitee_id, b.outcome, b.amount, b.event_time AS decided_at
FROM b
JOIN first fi ON fi.user_id = b.user_id
JOIN star_dim_users di ON di.user_id = b.user_id
 AND (di.valid_from <= b.event_time OR di.users_sk = fi.users_sk)
 AND (di.valid_to IS NULL OR b.event_time < di.valid_to)
JOIN first fe ON fe.user_id = b.invitee_id
JOIN star_dim_users de ON de.user_id = b.invitee_id
 AND (de.valid_from <= b.event_time OR de.users_sk = fe.users_sk)
 AND (de.valid_to IS NULL OR b.event_time < de.valid_to);
