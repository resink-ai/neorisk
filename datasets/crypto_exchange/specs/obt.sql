-- One big table per fact grain. obt_trades is one wide row per trade with both sides: the
-- maker's and taker's order terms and traders' segments, and the buyer's and seller's
-- segments (nothing about a trader changes in the log, so "as of the trade" is the creation
-- value). obt_orders is one row per order id (accepted or rejected) with its trader's segment
-- and the lifecycle flattened into milestone times, trade counts, filled quantity and the
-- final outcome. obt_deposits is one row per deposit with the trader's segment.

-- table: obt_trades
SELECT t.trade_id, t.event_time AS traded_at, CAST(t.event_time AS DATE) AS traded_date,
       t.symbol, t.taker_side, t.price, t.qty, CAST(t.price * t.qty AS BIGINT) AS notional,
       t.maker_order AS maker_order_id, m.side AS maker_order_side,
       m."type" AS maker_order_type, m.price AS maker_order_price, m.qty AS maker_order_qty,
       m.trader_id AS maker_trader_id, mt.segment AS maker_segment,
       t.taker_order AS taker_order_id, k.side AS taker_order_side,
       k."type" AS taker_order_type, k.price AS taker_order_price, k.qty AS taker_order_qty,
       k.trader_id AS taker_trader_id, kt.segment AS taker_segment,
       t.buyer_id, b.segment AS buyer_segment, t.seller_id, s.segment AS seller_segment
FROM trade t
JOIN order_accepted m ON m.order_id = t.maker_order
JOIN traders mt ON mt.trader_id = m.trader_id
JOIN order_accepted k ON k.order_id = t.taker_order
JOIN traders kt ON kt.trader_id = k.trader_id
JOIN traders b ON b.trader_id = t.buyer_id
JOIN traders s ON s.trader_id = t.seller_id;

-- table: obt_orders
-- Outcome as in the star's lifecycle: rejected; filled; cancelled_user or cancelled_ioc;
-- else resting or partial_resting at the end of the log.
WITH legs AS (
    SELECT maker_order AS order_id, 'maker' AS role, qty, price, event_time FROM trade
    UNION ALL
    SELECT taker_order, 'taker', qty, price, event_time FROM trade
), tr AS (
    SELECT order_id, CAST(count(*) AS BIGINT) AS trades,
           CAST(count(*) FILTER (WHERE role = 'maker') AS BIGINT) AS maker_trades,
           CAST(count(*) FILTER (WHERE role = 'taker') AS BIGINT) AS taker_trades,
           CAST(sum(qty) AS BIGINT) AS filled_qty,
           CAST(sum(price * qty) AS BIGINT) AS filled_notional,
           min(event_time) AS first_trade_at, max(event_time) AS last_trade_at
    FROM legs GROUP BY order_id
), o AS (
    SELECT order_id, trader_id, symbol, side, "type", price, qty, event_time AS submitted_at,
           event_time AS accepted_at, CAST(NULL AS TIMESTAMPTZ) AS rejected_at,
           CAST(NULL AS VARCHAR) AS reject_reason
    FROM order_accepted
    UNION ALL
    SELECT order_id, trader_id, symbol, side, "type", price, qty, event_time, NULL, event_time,
           reason
    FROM order_rejected
), w AS (
    SELECT o.order_id, o.trader_id, t.segment AS trader_segment, o.symbol, o.side, o."type",
           o.price, o.qty, o.submitted_at, o.accepted_at, o.rejected_at, o.reject_reason,
           coalesce(tr.trades, 0) AS trades, coalesce(tr.maker_trades, 0) AS maker_trades,
           coalesce(tr.taker_trades, 0) AS taker_trades,
           coalesce(tr.filled_qty, 0) AS filled_qty,
           coalesce(tr.filled_notional, 0) AS filled_notional,
           tr.first_trade_at, tr.last_trade_at, f.event_time AS filled_at,
           c.event_time AS cancelled_at, c.reason AS cancel_reason, c.qty_left AS cancelled_qty
    FROM o
    JOIN traders t USING (trader_id)
    LEFT JOIN tr USING (order_id)
    LEFT JOIN order_filled f USING (order_id)
    LEFT JOIN order_cancelled c USING (order_id)
), s AS (
    SELECT *,
           CASE WHEN rejected_at IS NOT NULL THEN 'rejected'
                WHEN filled_at IS NOT NULL THEN 'filled'
                WHEN cancelled_at IS NOT NULL THEN 'cancelled_' || cancel_reason
                WHEN filled_qty > 0 THEN 'partial_resting'
                ELSE 'resting' END AS outcome
    FROM w
)
SELECT *,
       CASE WHEN outcome IN ('resting', 'partial_resting') THEN qty - filled_qty
            ELSE CAST(0 AS BIGINT) END AS resting_qty
FROM s;

-- table: obt_deposits
SELECT d.event_id AS deposit_id, d.event_time AS deposited_at, d.trader_id,
       t.segment AS trader_segment, d.symbol, d.asset, d.amount
FROM funds_deposited d JOIN traders t USING (trader_id);
