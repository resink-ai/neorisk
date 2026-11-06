-- The outcome is derived from the status satellite (an order has at most one terminal row:
-- rejected, filled or cancelled) and, for an order still open, from its trades.
WITH f AS (
    SELECT order_hk, sum(qty) AS filled_qty FROM (
        SELECT t.maker_order_hk AS order_hk, s.qty
        FROM dv_link_trade t JOIN dv_sat_trade_details s USING (trade_hk)
        UNION ALL
        SELECT t.taker_order_hk, s.qty
        FROM dv_link_trade t JOIN dv_sat_trade_details s USING (trade_hk)) GROUP BY order_hk
), st AS (
    SELECT order_hk,
           max(CASE WHEN order_status = 'rejected' THEN 'rejected'
                    WHEN order_status = 'filled' THEN 'filled'
                    WHEN order_status = 'cancelled' THEN 'cancelled_' || reason END) AS terminal
    FROM dv_sat_orders_status GROUP BY order_hk
), s AS (
    SELECT d."type", d.qty, coalesce(f.filled_qty, 0) AS filled_qty,
           coalesce(st.terminal,
                    CASE WHEN f.filled_qty > 0 THEN 'partial_resting' ELSE 'resting' END)
               AS outcome
    FROM dv_hub_orders h
    JOIN dv_sat_orders_details d USING (order_hk)
    JOIN st USING (order_hk)
    LEFT JOIN f USING (order_hk)
)
SELECT "type", outcome, CAST(count(*) AS BIGINT) AS orders, CAST(sum(qty) AS BIGINT) AS qty,
       CAST(sum(filled_qty) AS BIGINT) AS filled_qty
FROM s
GROUP BY "type", outcome;
