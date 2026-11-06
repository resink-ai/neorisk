-- Orders by type and final outcome, with their ordered and filled quantity. Outcomes:
-- rejected; filled; cancelled_user or cancelled_ioc; and, at the end of the log, an accepted
-- order with neither is partial_resting if anything traded, else resting. Filled quantity is
-- the order's trades on either side (maker or taker).
WITH o AS (
    SELECT order_id, "type", qty, FALSE AS rejected FROM sim.order_accepted
    UNION ALL
    SELECT order_id, "type", qty, TRUE FROM sim.order_rejected
), f AS (
    SELECT order_id, sum(qty) AS filled_qty FROM (
        SELECT maker_order AS order_id, qty FROM sim.trade
        UNION ALL
        SELECT taker_order, qty FROM sim.trade) GROUP BY order_id
), s AS (
    SELECT o."type", o.qty, coalesce(f.filled_qty, 0) AS filled_qty,
           CASE WHEN o.rejected THEN 'rejected'
                WHEN EXISTS (SELECT 1 FROM sim.order_filled x WHERE x.order_id = o.order_id)
                    THEN 'filled'
                WHEN EXISTS (SELECT 1 FROM sim.order_cancelled x
                             WHERE x.order_id = o.order_id AND x.reason = 'user')
                    THEN 'cancelled_user'
                WHEN EXISTS (SELECT 1 FROM sim.order_cancelled x
                             WHERE x.order_id = o.order_id AND x.reason = 'ioc')
                    THEN 'cancelled_ioc'
                WHEN f.filled_qty > 0 THEN 'partial_resting'
                ELSE 'resting' END AS outcome
    FROM o LEFT JOIN f USING (order_id)
)
SELECT "type", outcome, CAST(count(*) AS BIGINT) AS orders, CAST(sum(qty) AS BIGINT) AS qty,
       CAST(sum(filled_qty) AS BIGINT) AS filled_qty
FROM s
GROUP BY "type", outcome;
