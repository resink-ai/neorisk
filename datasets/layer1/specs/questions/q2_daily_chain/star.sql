WITH b AS (
    SELECT CAST(produced_at AS DATE) AS chain_date, CAST(count(*) AS BIGINT) AS blocks,
           CAST(sum(gas_used) AS BIGINT) AS gas_used
    FROM star_fact_blocks GROUP BY chain_date
), i AS (
    SELECT CAST(included_at AS DATE) AS chain_date, CAST(count(*) AS BIGINT) AS included_txs,
           CAST(sum(fee) AS BIGINT) AS fees
    FROM star_fact_tx_inclusions GROUP BY chain_date
)
SELECT b.chain_date, b.blocks, coalesce(i.included_txs, 0) AS included_txs, b.gas_used,
       coalesce(i.fees, CAST(0 AS BIGINT)) AS fees
FROM b LEFT JOIN i USING (chain_date);
