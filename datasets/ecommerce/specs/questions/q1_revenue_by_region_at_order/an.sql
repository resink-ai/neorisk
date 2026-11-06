WITH o AS (
    SELECT a.order_id, m.amount,
           (SELECT r.region FROM an_users_region r
            WHERE r.user_id = b.user_id AND r.changed_at <= a.placed_at
            ORDER BY r.changed_at DESC LIMIT 1) AS region
    FROM an_orders a
    JOIN an_orders_placedby_users b USING (order_id)
    JOIN an_orders_amount m USING (order_id)
)
SELECT region, CAST(count(*) AS BIGINT) AS orders, CAST(sum(amount) AS BIGINT) AS amount
FROM o GROUP BY region;
