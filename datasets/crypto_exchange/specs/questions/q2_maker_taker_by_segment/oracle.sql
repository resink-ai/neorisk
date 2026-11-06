-- Per trader segment: trades and quantity on the maker (resting) side and on the taker
-- (incoming) side. The taker is the buyer when taker_side is 'buy', else the seller; the
-- maker is the other party.
WITH legs AS (
    SELECT CASE WHEN taker_side = 'buy' THEN seller_id ELSE buyer_id END AS trader_id,
           'maker' AS role, qty
    FROM sim.trade
    UNION ALL
    SELECT CASE WHEN taker_side = 'buy' THEN buyer_id ELSE seller_id END, 'taker', qty
    FROM sim.trade
)
SELECT t.segment,
       CAST(count(*) FILTER (WHERE l.role = 'maker') AS BIGINT) AS maker_trades,
       CAST(coalesce(sum(l.qty) FILTER (WHERE l.role = 'maker'), 0) AS BIGINT) AS maker_qty,
       CAST(count(*) FILTER (WHERE l.role = 'taker') AS BIGINT) AS taker_trades,
       CAST(coalesce(sum(l.qty) FILTER (WHERE l.role = 'taker'), 0) AS BIGINT) AS taker_qty
FROM legs l JOIN sim.traders t USING (trader_id)
GROUP BY t.segment;
