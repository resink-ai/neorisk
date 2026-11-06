WITH o AS (
    SELECT l.order_hk, l.load_dts, s.amount,
           (SELECT r.region FROM dv_sat_users_region r
            WHERE r.user_hk = l.user_hk AND r.load_dts <= l.load_dts
            ORDER BY r.load_dts DESC LIMIT 1) AS region
    FROM dv_link_order l JOIN dv_sat_orders_details s USING (order_hk)
)
SELECT region, CAST(count(*) AS BIGINT) AS orders, CAST(sum(amount) AS BIGINT) AS amount
FROM o GROUP BY region;
