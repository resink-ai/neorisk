-- The drop's reason is feature_3 of dropped_tx; the value it tried to move is feature_3 of
-- the sender's submitted_tx with the same tx_id (feature_1).
WITH sub AS (
    SELECT customer, feature_1 AS tx_id, CAST(feature_3 AS BIGINT) AS value
    FROM act_account_stream WHERE activity = 'submitted_tx'
)
SELECT d.feature_3 AS reason, a.kind AS sender_kind, CAST(count(*) AS BIGINT) AS dropped_txs,
       CAST(count(DISTINCT d.customer) AS BIGINT) AS senders,
       CAST(sum(s.value) AS BIGINT) AS value
FROM act_account_stream d
JOIN act_account a USING (customer)
JOIN sub s ON s.customer = d.customer AND s.tx_id = d.feature_1
WHERE d.activity = 'dropped_tx'
GROUP BY d.feature_3, a.kind;
