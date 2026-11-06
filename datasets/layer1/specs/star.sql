-- Star schema (Kimball). Accounts never change in the log, so the one dimension is static and
-- facts carry the natural keys (account ids are plain integers in the pack, not references).
-- Block is a column, not a dimension: simkit has no blocks table to check one against, and
-- star_fact_blocks already holds a block's only attributes. One transaction fact per business
-- event, and one accumulating snapshot, star_fact_tx_lifecycle: a row per transaction with its
-- terms, the block that settled it, and its final status. Amounts are gwei.

-- table: star_dim_accounts
SELECT account_id, kind, created_at FROM accounts;

-- table: star_fact_genesis_allocations
SELECT event_id AS allocation_id, account_id, amount, event_time AS allocated_at
FROM genesis_allocated;

-- table: star_fact_tx_receipts
SELECT tx_id, from_account, to_account, nonce, value, gas_limit, kind,
       event_time AS received_at
FROM tx_received;

-- table: star_fact_tx_inclusions
SELECT tx_id, block, from_account, nonce, gas_used, fee, status, event_time AS included_at
FROM tx_included;

-- table: star_fact_tx_drops
SELECT tx_id, block, from_account, reason, event_time AS dropped_at FROM tx_dropped;

-- table: star_fact_transfers
SELECT tx_id, from_account, to_account, value, event_time AS transferred_at
FROM transfer_log;

-- table: star_fact_blocks
-- txs counts every transaction the block processed, dropped ones included; gas_used only the
-- included ones.
SELECT block, txs, gas_used, event_time AS produced_at FROM block_produced;

-- table: star_fact_tx_lifecycle
-- status: success or reverted (included), dropped (with drop_reason), else pending (received
-- but not yet in a block at the end of the log). settled_at is the time of the block that
-- included or dropped it. fee is paid by every included transaction, reverted ones too;
-- transferred_value is the value that moved: the value of a successful transaction, 0 for a
-- reverted call, a drop or a pending transaction (a successful transfer's value is exactly
-- its transfer log's, by the pack's laws).
WITH l AS (
    SELECT r.tx_id, r.from_account, r.to_account, r.kind, r.nonce, r.value, r.gas_limit,
           r.received_at, coalesce(i.block, d.block) AS block,
           coalesce(i.included_at, d.dropped_at) AS settled_at, i.included_at, d.dropped_at,
           CASE WHEN i.tx_id IS NOT NULL THEN i.status
                WHEN d.tx_id IS NOT NULL THEN 'dropped'
                ELSE 'pending' END AS status,
           d.reason AS drop_reason, i.gas_used, i.fee
    FROM star_fact_tx_receipts r
    LEFT JOIN star_fact_tx_inclusions i USING (tx_id)
    LEFT JOIN star_fact_tx_drops d USING (tx_id)
)
SELECT *,
       CASE WHEN status = 'success' THEN value ELSE CAST(0 AS BIGINT) END
           AS transferred_value
FROM l;
