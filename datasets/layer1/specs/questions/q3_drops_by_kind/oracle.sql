-- Dropped transactions by drop reason and the sender account's kind: how many, from how many
-- distinct senders, and the value they tried to move (gwei, from their receipt).
SELECT d.reason, a.kind AS sender_kind, CAST(count(*) AS BIGINT) AS dropped_txs,
       CAST(count(DISTINCT d.from_account) AS BIGINT) AS senders,
       CAST(sum(r.value) AS BIGINT) AS value
FROM sim.tx_dropped d
JOIN sim.accounts a ON a.account_id = d.from_account
JOIN sim.tx_received r USING (tx_id)
GROUP BY d.reason, a.kind;
