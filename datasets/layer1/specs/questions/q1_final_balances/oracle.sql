-- Every account's balance at the end of the log, in gwei: its genesis allocation, plus the
-- values transferred to it, minus the values it transferred and the fees it paid. Only
-- successful transactions move value (a transfer log exists for those alone); a reverted call
-- moves nothing but still pays its fee. Contracts get no genesis and end at 0.
WITH m AS (
    SELECT account_id, amount AS v FROM sim.genesis_allocated
    UNION ALL SELECT to_account, value FROM sim.transfer_log
    UNION ALL SELECT from_account, -value FROM sim.transfer_log
    UNION ALL SELECT from_account, -fee FROM sim.tx_included
)
SELECT a.account_id, a.kind, CAST(coalesce(sum(m.v), 0) AS BIGINT) AS balance
FROM sim.accounts a LEFT JOIN m USING (account_id)
GROUP BY a.account_id, a.kind;
