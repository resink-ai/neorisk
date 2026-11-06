-- A trade's maker and taker orders lead to their traders through the order-trader link.
WITH legs AS (
    SELECT t.maker_order_hk AS order_hk, 'maker' AS role, s.qty
    FROM dv_link_trade t JOIN dv_sat_trade_details s USING (trade_hk)
    UNION ALL
    SELECT t.taker_order_hk, 'taker', s.qty
    FROM dv_link_trade t JOIN dv_sat_trade_details s USING (trade_hk)
)
SELECT p.segment,
       CAST(count(*) FILTER (WHERE l.role = 'maker') AS BIGINT) AS maker_trades,
       CAST(coalesce(sum(l.qty) FILTER (WHERE l.role = 'maker'), 0) AS BIGINT) AS maker_qty,
       CAST(count(*) FILTER (WHERE l.role = 'taker') AS BIGINT) AS taker_trades,
       CAST(coalesce(sum(l.qty) FILTER (WHERE l.role = 'taker'), 0) AS BIGINT) AS taker_qty
FROM legs l
JOIN dv_link_order_trader ot USING (order_hk)
JOIN dv_sat_traders_profile p ON p.trader_hk = ot.trader_hk
GROUP BY p.segment;
