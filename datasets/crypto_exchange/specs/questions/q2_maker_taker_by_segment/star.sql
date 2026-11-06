WITH legs AS (
    SELECT maker_trader_id AS trader_id, 'maker' AS role, qty FROM star_fact_trades
    UNION ALL
    SELECT taker_trader_id, 'taker', qty FROM star_fact_trades
)
SELECT d.segment,
       CAST(count(*) FILTER (WHERE l.role = 'maker') AS BIGINT) AS maker_trades,
       CAST(coalesce(sum(l.qty) FILTER (WHERE l.role = 'maker'), 0) AS BIGINT) AS maker_qty,
       CAST(count(*) FILTER (WHERE l.role = 'taker') AS BIGINT) AS taker_trades,
       CAST(coalesce(sum(l.qty) FILTER (WHERE l.role = 'taker'), 0) AS BIGINT) AS taker_qty
FROM legs l JOIN star_dim_traders d USING (trader_id)
GROUP BY d.segment;
