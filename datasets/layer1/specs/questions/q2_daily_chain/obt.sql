SELECT produced_date AS chain_date, CAST(count(*) AS BIGINT) AS blocks,
       CAST(sum(included_txs) AS BIGINT) AS included_txs, CAST(sum(gas_used) AS BIGINT) AS gas_used,
       CAST(sum(fees) AS BIGINT) AS fees
FROM obt_blocks
GROUP BY produced_date;
