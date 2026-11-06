SELECT drop_reason AS reason, from_kind AS sender_kind, CAST(count(*) AS BIGINT) AS dropped_txs,
       CAST(count(DISTINCT from_account) AS BIGINT) AS senders,
       CAST(sum(value) AS BIGINT) AS value
FROM obt_transactions
WHERE status = 'dropped'
GROUP BY drop_reason, from_kind;
