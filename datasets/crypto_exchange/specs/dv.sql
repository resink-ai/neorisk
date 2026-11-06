-- Data Vault 2.0. Hash keys are md5 of the business key as text; link keys md5 of the parent
-- hash keys (and a dependent child key) joined by '||'; hashdiff is md5 of the attributes
-- joined by '||' with nulls as ''. Insert-only: load_dts is the event time, record_source
-- the log event type. Hubs for traders and orders (business key order_id; an order is first
-- seen when the book accepts or rejects it). A trade is a link between its maker and taker
-- orders and its buyer and seller, with the trade id as dependent child key; a deposit is a
-- link on its trader with the event id as dependent child key. An order's life is one
-- status satellite, a row per state (open, rejected, filled, cancelled). Symbol is an
-- attribute, not a hub: simkit has no symbols table to check a hub against.

-- table: dv_hub_traders
SELECT md5(CAST(trader_id AS VARCHAR)) AS trader_hk, trader_id, created_at AS load_dts,
       'traders_created' AS record_source
FROM traders;

-- table: dv_hub_orders
WITH o AS (
    SELECT order_id, event_time, event_type FROM order_accepted
    UNION ALL
    SELECT order_id, event_time, event_type FROM order_rejected
)
SELECT md5(CAST(order_id AS VARCHAR)) AS order_hk, order_id, event_time AS load_dts,
       event_type AS record_source
FROM o;

-- table: dv_link_order_trader
WITH k AS (
    SELECT md5(CAST(order_id AS VARCHAR)) AS order_hk,
           md5(CAST(trader_id AS VARCHAR)) AS trader_hk, event_time, event_type
    FROM order_accepted
    UNION ALL
    SELECT md5(CAST(order_id AS VARCHAR)), md5(CAST(trader_id AS VARCHAR)), event_time,
           event_type
    FROM order_rejected
)
SELECT md5(order_hk || '||' || trader_hk) AS order_trader_hk, order_hk, trader_hk,
       event_time AS load_dts, event_type AS record_source
FROM k;

-- table: dv_link_trade
WITH k AS (SELECT md5(CAST(maker_order AS VARCHAR)) AS maker_order_hk,
                  md5(CAST(taker_order AS VARCHAR)) AS taker_order_hk,
                  md5(CAST(buyer_id AS VARCHAR)) AS buyer_hk,
                  md5(CAST(seller_id AS VARCHAR)) AS seller_hk, trade_id, event_time
           FROM trade)
SELECT md5(maker_order_hk || '||' || taker_order_hk || '||' || buyer_hk || '||' || seller_hk
           || '||' || CAST(trade_id AS VARCHAR)) AS trade_hk,
       maker_order_hk, taker_order_hk, buyer_hk, seller_hk, trade_id, event_time AS load_dts,
       'trade' AS record_source
FROM k;

-- table: dv_link_deposit
SELECT md5(md5(CAST(trader_id AS VARCHAR)) || '||' || CAST(event_id AS VARCHAR)) AS deposit_hk,
       md5(CAST(trader_id AS VARCHAR)) AS trader_hk, event_id AS deposit_id,
       event_time AS load_dts, 'funds_deposited' AS record_source
FROM funds_deposited;

-- table: dv_sat_traders_profile
SELECT md5(CAST(trader_id AS VARCHAR)) AS trader_hk, created_at AS load_dts,
       'traders_created' AS record_source, md5(coalesce(segment, '')) AS hashdiff, segment
FROM traders;

-- table: dv_sat_orders_details
-- The order's terms as submitted, from its acceptance or its rejection.
WITH o AS (
    SELECT order_id, event_time, event_type, symbol, side, "type", price, qty
    FROM order_accepted
    UNION ALL
    SELECT order_id, event_time, event_type, symbol, side, "type", price, qty
    FROM order_rejected
)
SELECT md5(CAST(order_id AS VARCHAR)) AS order_hk, event_time AS load_dts,
       event_type AS record_source,
       md5(coalesce(symbol, '') || '||' || coalesce(side, '') || '||' || coalesce("type", '')
           || '||' || coalesce(CAST(price AS VARCHAR), '') || '||'
           || coalesce(CAST(qty AS VARCHAR), '')) AS hashdiff,
       symbol, side, "type", price, qty
FROM o;

-- table: dv_sat_orders_status
-- One row per state of the order: open (accepted) or rejected (with its reason), then filled
-- or cancelled (with its reason and the quantity left). An order still open at the end of the
-- log has only its open row.
WITH s AS (
    SELECT order_id, event_time, seq, event_type, 'open' AS order_status,
           CAST(NULL AS VARCHAR) AS reason, CAST(NULL AS BIGINT) AS qty_left
    FROM order_accepted
    UNION ALL
    SELECT order_id, event_time, seq, event_type, 'rejected', reason, NULL FROM order_rejected
    UNION ALL
    SELECT order_id, event_time, seq, event_type, 'filled', NULL, NULL FROM order_filled
    UNION ALL
    SELECT order_id, event_time, seq, event_type, 'cancelled', reason, qty_left
    FROM order_cancelled
), d AS (
    SELECT md5(CAST(order_id AS VARCHAR)) AS order_hk, event_time AS load_dts, seq,
           event_type AS record_source,
           md5(order_status || '||' || coalesce(reason, '') || '||'
               || coalesce(CAST(qty_left AS VARCHAR), '')) AS hashdiff,
           order_status, reason, qty_left
    FROM s
)
SELECT order_hk, load_dts, record_source, hashdiff, order_status, reason, qty_left
FROM d
QUALIFY lag(hashdiff) OVER (PARTITION BY order_hk ORDER BY load_dts, seq)
        IS DISTINCT FROM hashdiff;

-- table: dv_sat_trade_details
SELECT md5(md5(CAST(maker_order AS VARCHAR)) || '||' || md5(CAST(taker_order AS VARCHAR))
           || '||' || md5(CAST(buyer_id AS VARCHAR)) || '||' || md5(CAST(seller_id AS VARCHAR))
           || '||' || CAST(trade_id AS VARCHAR)) AS trade_hk,
       event_time AS load_dts, 'trade' AS record_source,
       md5(coalesce(symbol, '') || '||' || coalesce(taker_side, '') || '||'
           || coalesce(CAST(price AS VARCHAR), '') || '||' || coalesce(CAST(qty AS VARCHAR), ''))
           AS hashdiff,
       symbol, taker_side, price, qty
FROM trade;

-- table: dv_sat_deposit_details
SELECT md5(md5(CAST(trader_id AS VARCHAR)) || '||' || CAST(event_id AS VARCHAR)) AS deposit_hk,
       event_time AS load_dts, 'funds_deposited' AS record_source,
       md5(coalesce(symbol, '') || '||' || coalesce(asset, '') || '||'
           || coalesce(CAST(amount AS VARCHAR), '')) AS hashdiff,
       symbol, asset, amount
FROM funds_deposited;
