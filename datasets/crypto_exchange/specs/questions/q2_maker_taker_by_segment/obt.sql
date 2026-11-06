WITH legs AS (
    SELECT maker_segment AS segment, 'maker' AS role, qty FROM obt_trades
    UNION ALL
    SELECT taker_segment, 'taker', qty FROM obt_trades
)
SELECT segment,
       CAST(count(*) FILTER (WHERE role = 'maker') AS BIGINT) AS maker_trades,
       CAST(coalesce(sum(qty) FILTER (WHERE role = 'maker'), 0) AS BIGINT) AS maker_qty,
       CAST(count(*) FILTER (WHERE role = 'taker') AS BIGINT) AS taker_trades,
       CAST(coalesce(sum(qty) FILTER (WHERE role = 'taker'), 0) AS BIGINT) AS taker_qty
FROM legs
GROUP BY segment;
