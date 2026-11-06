-- Activity schema. One stream, act_subscriber_stream: one row per subscription event of a
-- subscriber (the customer), in the standard columns. activity_id is the log's event_id;
-- the features are text:
--   started_subscription   feature_1 plan, feature_2 price (cents)
--   converted_trial        (none)
--   paid_invoice           feature_1 cycle, feature_2 attempt; revenue_impact = amount
--   failed_charge          feature_1 cycle, feature_2 attempt, feature_3 reason
--   cancelled_subscription feature_1 reason, feature_2 cycles_paid
-- revenue_impact is the amount of a paid invoice, else null (a failed charge earns
-- nothing; its amount is the subscription's price). link is null: no activity has a URL.
-- activity_occurrence counts the customer's activities of that kind in ts order (ties by
-- activity_id); activity_repeated_at is the ts of the customer's next one, else null.
-- act_subscriber is the customer table.

-- table: act_subscriber
SELECT subscriber_id AS customer, plan, signup_channel, created_at FROM subscribers;

-- table: act_subscriber_stream
WITH a AS (
    SELECT event_id AS activity_id, event_time AS ts, subscriber_id AS customer,
           'started_subscription' AS activity, plan AS feature_1,
           CAST(price AS VARCHAR) AS feature_2, CAST(NULL AS VARCHAR) AS feature_3,
           CAST(NULL AS BIGINT) AS revenue_impact
    FROM subscription_started
    UNION ALL
    SELECT event_id, event_time, subscriber_id, 'converted_trial', NULL, NULL, NULL, NULL
    FROM trial_converted
    UNION ALL
    SELECT event_id, event_time, subscriber_id, 'paid_invoice', CAST(cycle AS VARCHAR),
           CAST(attempt AS VARCHAR), NULL, amount
    FROM invoice_paid
    UNION ALL
    SELECT event_id, event_time, subscriber_id, 'failed_charge', CAST(cycle AS VARCHAR),
           CAST(attempt AS VARCHAR), reason, NULL
    FROM charge_failed
    UNION ALL
    SELECT event_id, event_time, subscriber_id, 'cancelled_subscription', reason,
           CAST(cycles_paid AS VARCHAR), NULL, NULL
    FROM subscription_cancelled
)
SELECT activity_id, ts, customer, activity, feature_1, feature_2, feature_3,
       revenue_impact, CAST(NULL AS VARCHAR) AS link,
       row_number() OVER (PARTITION BY customer, activity ORDER BY ts, activity_id)
           AS activity_occurrence,
       lead(ts) OVER (PARTITION BY customer, activity ORDER BY ts, activity_id)
           AS activity_repeated_at
FROM a;
