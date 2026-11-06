-- A block is every inclusion and drop that names it in feature_2, all at the block's time;
-- a block that only dropped transactions is still a block. feature_3 is gas used on an
-- inclusion but the reason on a drop, so it is cast only on inclusions.
SELECT CAST(ts AS DATE) AS chain_date, CAST(count(DISTINCT feature_2) AS BIGINT) AS blocks,
       CAST(count(*) FILTER (WHERE activity <> 'dropped_tx') AS BIGINT) AS included_txs,
       CAST(coalesce(sum(CASE WHEN activity <> 'dropped_tx' THEN CAST(feature_3 AS BIGINT) END),
                     0) AS BIGINT) AS gas_used,
       CAST(coalesce(-sum(revenue_impact), 0) AS BIGINT) AS fees
FROM act_account_stream
WHERE activity IN ('included_tx', 'reverted_tx', 'dropped_tx')
GROUP BY chain_date;
