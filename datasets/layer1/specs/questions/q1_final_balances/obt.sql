WITH m AS (
    SELECT account_id, genesis_amount AS v FROM obt_accounts WHERE genesis_amount IS NOT NULL
    UNION ALL SELECT to_account, transferred_value FROM obt_transactions
    UNION ALL SELECT from_account, -transferred_value FROM obt_transactions
    UNION ALL SELECT from_account, -fee FROM obt_transactions WHERE fee IS NOT NULL
)
SELECT a.account_id, a.kind, CAST(coalesce(sum(m.v), 0) AS BIGINT) AS balance
FROM obt_accounts a LEFT JOIN m USING (account_id)
GROUP BY a.account_id, a.kind;
