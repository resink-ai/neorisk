-- Activity schema. One stream, act_account_stream: one row per thing that happens to an
-- account (the customer), in the standard columns. activity_id is the log's event_id; the
-- features are text:
--   received_genesis  (none)                                 revenue_impact = +amount
--   submitted_tx      feature_1 tx_id, feature_2 kind, feature_3 value
--   included_tx       feature_1 tx_id, feature_2 block, feature_3 gas_used; revenue_impact = -fee
--   reverted_tx       feature_1 tx_id, feature_2 block, feature_3 gas_used; revenue_impact = -fee
--   dropped_tx        feature_1 tx_id, feature_2 block, feature_3 reason
--   sent_value        feature_1 tx_id, feature_2 to_account;  revenue_impact = -value
--   received_value    feature_1 tx_id, feature_2 from_account; revenue_impact = +value
-- revenue_impact is the signed change to the customer's balance in gwei, else null, so an
-- account's balance at any time is the sum of its revenue_impact up to then. A transfer log
-- is two activities, sent_value on the sender and received_value on the receiver, sharing
-- the log's event_id: (activity_id, activity) is the stream's key. A block has no account:
-- its number is feature_2 of every inclusion and drop it settled, and all of them carry the
-- block's time as ts. link is null: no activity has a URL. activity_occurrence counts the
-- customer's activities of that kind in ts order (ties by activity_id); activity_repeated_at
-- is the ts of the customer's next one, else null. act_account is the customer table.

-- table: act_account
SELECT account_id AS customer, kind, created_at FROM accounts;

-- table: act_account_stream
WITH a AS (
    SELECT event_id AS activity_id, event_time AS ts, account_id AS customer,
           'received_genesis' AS activity, CAST(NULL AS VARCHAR) AS feature_1,
           CAST(NULL AS VARCHAR) AS feature_2, CAST(NULL AS VARCHAR) AS feature_3,
           amount AS revenue_impact
    FROM genesis_allocated
    UNION ALL
    SELECT event_id, event_time, from_account, 'submitted_tx', CAST(tx_id AS VARCHAR), kind,
           CAST(value AS VARCHAR), NULL
    FROM tx_received
    UNION ALL
    SELECT event_id, event_time, from_account,
           CASE WHEN status = 'success' THEN 'included_tx' ELSE 'reverted_tx' END,
           CAST(tx_id AS VARCHAR), CAST(block AS VARCHAR), CAST(gas_used AS VARCHAR), -fee
    FROM tx_included
    UNION ALL
    SELECT event_id, event_time, from_account, 'dropped_tx', CAST(tx_id AS VARCHAR),
           CAST(block AS VARCHAR), reason, NULL
    FROM tx_dropped
    UNION ALL
    SELECT event_id, event_time, from_account, 'sent_value', CAST(tx_id AS VARCHAR),
           CAST(to_account AS VARCHAR), NULL, -value
    FROM transfer_log
    UNION ALL
    SELECT event_id, event_time, to_account, 'received_value', CAST(tx_id AS VARCHAR),
           CAST(from_account AS VARCHAR), NULL, value
    FROM transfer_log
)
SELECT activity_id, ts, customer, activity, feature_1, feature_2, feature_3,
       revenue_impact, CAST(NULL AS VARCHAR) AS link,
       row_number() OVER (PARTITION BY customer, activity ORDER BY ts, activity_id)
           AS activity_occurrence,
       lead(ts) OVER (PARTITION BY customer, activity ORDER BY ts, activity_id)
           AS activity_repeated_at
FROM a;
