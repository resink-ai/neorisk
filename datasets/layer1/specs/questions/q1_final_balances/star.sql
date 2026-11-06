WITH m AS (
    SELECT account_id, amount AS v FROM star_fact_genesis_allocations
    UNION ALL SELECT to_account, transferred_value FROM star_fact_tx_lifecycle
    UNION ALL SELECT from_account, -transferred_value FROM star_fact_tx_lifecycle
    UNION ALL SELECT from_account, -fee FROM star_fact_tx_lifecycle WHERE fee IS NOT NULL
)
SELECT a.account_id, a.kind, CAST(coalesce(sum(m.v), 0) AS BIGINT) AS balance
FROM star_dim_accounts a LEFT JOIN m USING (account_id)
GROUP BY a.account_id, a.kind;
