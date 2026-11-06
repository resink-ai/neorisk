-- Orders and amount by the user's region in force at order time.
WITH h AS (
    SELECT user_id, region, created_at AS ts, 0 AS ord FROM sim.users
    UNION ALL
    SELECT user_id, region, event_time, seq FROM sim.address_changed
), o AS (
    SELECT p.order_id, p.amount,
           (SELECT h.region FROM h WHERE h.user_id = p.user_id AND h.ts <= p.event_time
            ORDER BY h.ts DESC, h.ord DESC LIMIT 1) AS region
    FROM sim.order_placed p
)
SELECT region, CAST(count(*) AS BIGINT) AS orders, CAST(sum(amount) AS BIGINT) AS amount
FROM o GROUP BY region;
