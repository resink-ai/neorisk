-- Per UTC day of the block: blocks produced (non-empty ones: a block that only dropped
-- transactions counts), transactions included (successful or reverted), the gas they used
-- and the fees they paid, in gwei.
WITH b AS (
    SELECT CAST(event_time AS DATE) AS chain_date, CAST(count(*) AS BIGINT) AS blocks,
           CAST(sum(gas_used) AS BIGINT) AS gas_used
    FROM sim.block_produced GROUP BY chain_date
), i AS (
    SELECT CAST(event_time AS DATE) AS chain_date, CAST(count(*) AS BIGINT) AS included_txs,
           CAST(sum(fee) AS BIGINT) AS fees
    FROM sim.tx_included GROUP BY chain_date
)
SELECT b.chain_date, b.blocks, coalesce(i.included_txs, 0) AS included_txs, b.gas_used,
       coalesce(i.fees, CAST(0 AS BIGINT)) AS fees
FROM b LEFT JOIN i USING (chain_date);
