SELECT l.drop_reason AS reason, a.kind AS sender_kind, CAST(count(*) AS BIGINT) AS dropped_txs,
       CAST(count(DISTINCT l.from_account) AS BIGINT) AS senders,
       CAST(sum(l.value) AS BIGINT) AS value
FROM star_fact_tx_lifecycle l
JOIN star_dim_accounts a ON a.account_id = l.from_account
WHERE l.status = 'dropped'
GROUP BY l.drop_reason, a.kind;
