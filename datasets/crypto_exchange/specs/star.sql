-- Star schema (Kimball). Traders never change in the log, so the one dimension is static and
-- facts carry the natural keys. Symbol is a column, not a dimension: simkit has no symbols
-- table to check one against, and a symbol has no attribute beyond its name. One transaction
-- fact per business event, and one accumulating snapshot, star_fact_order_lifecycle: a row
-- per order id (accepted or rejected) with its terms, milestone times, filled quantity and
-- final outcome. Prices are integer ticks of $0.01, quantities integer lots; notional is
-- price * qty in ticks.

-- table: star_dim_traders
SELECT trader_id, segment, created_at FROM traders;

-- table: star_fact_deposits
SELECT event_id AS deposit_id, trader_id, symbol, asset, amount, event_time AS deposited_at
FROM funds_deposited;

-- table: star_fact_order_acceptances
SELECT order_id, trader_id, symbol, side, "type", price, qty, event_time AS accepted_at
FROM order_accepted;

-- table: star_fact_order_rejections
SELECT order_id, trader_id, symbol, side, "type", price, qty, reason,
       event_time AS rejected_at
FROM order_rejected;

-- table: star_fact_trades
-- Both sides of the fill: the maker (resting) and taker (incoming) orders and their traders,
-- and the buyer and seller.
SELECT t.trade_id, t.symbol, t.maker_order AS maker_order_id, m.trader_id AS maker_trader_id,
       t.taker_order AS taker_order_id, k.trader_id AS taker_trader_id, t.buyer_id,
       t.seller_id, t.taker_side, t.price, t.qty, CAST(t.price * t.qty AS BIGINT) AS notional,
       t.event_time AS traded_at
FROM trade t
JOIN order_accepted m ON m.order_id = t.maker_order
JOIN order_accepted k ON k.order_id = t.taker_order;

-- table: star_fact_order_fills
SELECT order_id, trader_id, symbol, event_time AS filled_at FROM order_filled;

-- table: star_fact_order_cancellations
SELECT order_id, trader_id, symbol, qty_left, reason, event_time AS cancelled_at
FROM order_cancelled;

-- table: star_fact_order_lifecycle
-- Outcome: rejected; filled; cancelled_user or cancelled_ioc (whatever was filled before);
-- at the end of the log, an accepted order with neither is resting (nothing filled) or
-- partial_resting (partly filled). resting_qty is what is still on the book at the end.
WITH legs AS (
    SELECT maker_order_id AS order_id, 'maker' AS role, qty, notional, traded_at
    FROM star_fact_trades
    UNION ALL
    SELECT taker_order_id, 'taker', qty, notional, traded_at FROM star_fact_trades
), tr AS (
    SELECT order_id, CAST(count(*) AS BIGINT) AS trades,
           CAST(count(*) FILTER (WHERE role = 'maker') AS BIGINT) AS maker_trades,
           CAST(count(*) FILTER (WHERE role = 'taker') AS BIGINT) AS taker_trades,
           CAST(sum(qty) AS BIGINT) AS filled_qty, CAST(sum(notional) AS BIGINT) AS filled_notional,
           min(traded_at) AS first_trade_at, max(traded_at) AS last_trade_at
    FROM legs GROUP BY order_id
), o AS (
    SELECT order_id, trader_id, symbol, side, "type", price, qty, accepted_at AS submitted_at,
           accepted_at, CAST(NULL AS TIMESTAMPTZ) AS rejected_at,
           CAST(NULL AS VARCHAR) AS reject_reason
    FROM star_fact_order_acceptances
    UNION ALL
    SELECT order_id, trader_id, symbol, side, "type", price, qty, rejected_at, NULL,
           rejected_at, reason
    FROM star_fact_order_rejections
), l AS (
    SELECT o.*, coalesce(tr.trades, 0) AS trades,
           coalesce(tr.maker_trades, 0) AS maker_trades,
           coalesce(tr.taker_trades, 0) AS taker_trades,
           coalesce(tr.filled_qty, 0) AS filled_qty,
           coalesce(tr.filled_notional, 0) AS filled_notional,
           tr.first_trade_at, tr.last_trade_at, f.filled_at, c.cancelled_at,
           c.reason AS cancel_reason, c.qty_left AS cancelled_qty
    FROM o
    LEFT JOIN tr USING (order_id)
    LEFT JOIN star_fact_order_fills f USING (order_id)
    LEFT JOIN star_fact_order_cancellations c USING (order_id)
), s AS (
    SELECT *,
           CASE WHEN rejected_at IS NOT NULL THEN 'rejected'
                WHEN filled_at IS NOT NULL THEN 'filled'
                WHEN cancelled_at IS NOT NULL THEN 'cancelled_' || cancel_reason
                WHEN filled_qty > 0 THEN 'partial_resting'
                ELSE 'resting' END AS outcome
    FROM l
)
SELECT *,
       CASE WHEN outcome IN ('resting', 'partial_resting') THEN qty - filled_qty
            ELSE CAST(0 AS BIGINT) END AS resting_qty
FROM s;
