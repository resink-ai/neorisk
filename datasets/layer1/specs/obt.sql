-- One big table per fact grain. obt_transactions is one wide row per transaction: its terms,
-- the sender's and receiver's account kinds (nothing about an account changes in the log, so
-- "as of the transaction" is the creation value), and the lifecycle flattened into the block
-- that settled it (number, time, its txs and gas), the final status and the fee. obt_blocks
-- is one row per produced block with what it included, reverted and dropped. obt_accounts is
-- one row per account with its genesis allocation (null for contracts, which get none).

-- table: obt_accounts
SELECT a.account_id, a.kind, a.created_at, g.amount AS genesis_amount,
       g.event_time AS genesis_at
FROM accounts a LEFT JOIN genesis_allocated g USING (account_id);

-- table: obt_transactions
-- status as in the star's lifecycle: success, reverted, dropped (with drop_reason), else
-- pending at the end of the log; transferred_value is the value of a successful
-- transaction, else 0.
WITH s AS (
    SELECT r.tx_id, r.event_time AS received_at, r.from_account, fa.kind AS from_kind,
           r.to_account, ta.kind AS to_kind, r.kind, r.nonce, r.value, r.gas_limit,
           CASE WHEN i.tx_id IS NOT NULL THEN i.status
                WHEN d.tx_id IS NOT NULL THEN 'dropped'
                ELSE 'pending' END AS status,
           d.reason AS drop_reason, coalesce(i.block, d.block) AS block,
           b.event_time AS settled_at, CAST(b.event_time AS DATE) AS settled_date,
           b.txs AS block_txs, b.gas_used AS block_gas_used, i.gas_used, i.fee
    FROM tx_received r
    JOIN accounts fa ON fa.account_id = r.from_account
    JOIN accounts ta ON ta.account_id = r.to_account
    LEFT JOIN tx_included i USING (tx_id)
    LEFT JOIN tx_dropped d USING (tx_id)
    LEFT JOIN block_produced b ON b.block = coalesce(i.block, d.block)
)
SELECT *,
       CASE WHEN status = 'success' THEN value ELSE CAST(0 AS BIGINT) END
           AS transferred_value
FROM s;

-- table: obt_blocks
WITH t AS (
    SELECT block, CAST(count(*) AS INTEGER) AS included_txs,
           CAST(count(*) FILTER (WHERE status = 'reverted') AS INTEGER) AS reverted_txs,
           CAST(sum(fee) AS BIGINT) AS fees
    FROM tx_included GROUP BY block
), d AS (
    SELECT block, CAST(count(*) AS INTEGER) AS dropped_txs FROM tx_dropped GROUP BY block
)
SELECT b.block, b.event_time AS produced_at, CAST(b.event_time AS DATE) AS produced_date,
       b.txs, coalesce(t.included_txs, 0) AS included_txs,
       coalesce(t.reverted_txs, 0) AS reverted_txs, coalesce(d.dropped_txs, 0) AS dropped_txs,
       b.gas_used, coalesce(t.fees, CAST(0 AS BIGINT)) AS fees
FROM block_produced b
LEFT JOIN t USING (block)
LEFT JOIN d USING (block);
