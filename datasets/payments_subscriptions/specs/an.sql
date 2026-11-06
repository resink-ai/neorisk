-- Anchor modeling (6NF). Anchors for subscribers, subscriptions (identity: the event_id of
-- subscription_started), paid invoices and failed charges, each with its identity and time;
-- one table per attribute; one tie per relation (an_<e1>_<role>_<e2>). Static attributes
-- have no changed_at; the historized ones have one row per change: the subscription's
-- status (subscription_started -> trial, trial_converted -> converted, invoice_paid ->
-- active, charge_failed -> dunning, subscription_cancelled -> cancelled), and the cancel
-- reason and cycles paid, set once at cancellation. No nulls: an absent value is an absent
-- row. A subscriber holds one subscription, so an invoice or a failure ties to the
-- subscription of its subscriber.

-- table: an_subscribers
SELECT subscriber_id, created_at FROM subscribers;

-- table: an_subscribers_plan
SELECT subscriber_id, plan FROM subscribers;

-- table: an_subscribers_signup_channel
SELECT subscriber_id, signup_channel FROM subscribers;

-- table: an_subscriptions
SELECT event_id AS subscription_id, event_time AS started_at FROM subscription_started;

-- table: an_subscriptions_heldby_subscribers
SELECT event_id AS subscription_id, subscriber_id FROM subscription_started;

-- table: an_subscriptions_plan
SELECT event_id AS subscription_id, plan FROM subscription_started;

-- table: an_subscriptions_price
SELECT event_id AS subscription_id, price FROM subscription_started;

-- table: an_subscriptions_status
WITH h AS (
    SELECT subscriber_id, event_time AS ts, seq, 'trial' AS status FROM subscription_started
    UNION ALL SELECT subscriber_id, event_time, seq, 'converted' FROM trial_converted
    UNION ALL SELECT subscriber_id, event_time, seq, 'active' FROM invoice_paid
    UNION ALL SELECT subscriber_id, event_time, seq, 'dunning' FROM charge_failed
    UNION ALL SELECT subscriber_id, event_time, seq, 'cancelled' FROM subscription_cancelled
), last AS (    -- two events at one instant: the later one (by seq) is the status at that time
    SELECT * FROM h
    QUALIFY row_number() OVER (PARTITION BY subscriber_id, ts ORDER BY seq DESC) = 1
)
SELECT t.subscription_id, l.status, l.ts AS changed_at
FROM last l JOIN an_subscriptions_heldby_subscribers t USING (subscriber_id)
QUALIFY lag(l.status) OVER (PARTITION BY t.subscription_id ORDER BY l.ts)
        IS DISTINCT FROM l.status;

-- table: an_subscriptions_cancel_reason
SELECT t.subscription_id, c.reason AS cancel_reason, c.event_time AS changed_at
FROM subscription_cancelled c JOIN an_subscriptions_heldby_subscribers t USING (subscriber_id);

-- table: an_subscriptions_cycles_paid
SELECT t.subscription_id, c.cycles_paid, c.event_time AS changed_at
FROM subscription_cancelled c JOIN an_subscriptions_heldby_subscribers t USING (subscriber_id);

-- table: an_invoices
SELECT event_id AS invoice_id, event_time AS paid_at FROM invoice_paid;

-- table: an_invoices_cycle
SELECT event_id AS invoice_id, cycle FROM invoice_paid;

-- table: an_invoices_attempt
SELECT event_id AS invoice_id, attempt FROM invoice_paid;

-- table: an_invoices_amount
SELECT event_id AS invoice_id, amount FROM invoice_paid;

-- table: an_invoices_for_subscriptions
SELECT i.event_id AS invoice_id, t.subscription_id
FROM invoice_paid i JOIN an_subscriptions_heldby_subscribers t USING (subscriber_id);

-- table: an_charge_failures
SELECT event_id AS failure_id, event_time AS failed_at FROM charge_failed;

-- table: an_charge_failures_cycle
SELECT event_id AS failure_id, cycle FROM charge_failed;

-- table: an_charge_failures_attempt
SELECT event_id AS failure_id, attempt FROM charge_failed;

-- table: an_charge_failures_amount
SELECT event_id AS failure_id, amount FROM charge_failed;

-- table: an_charge_failures_reason
SELECT event_id AS failure_id, reason FROM charge_failed;

-- table: an_charge_failures_for_subscriptions
SELECT f.event_id AS failure_id, t.subscription_id
FROM charge_failed f JOIN an_subscriptions_heldby_subscribers t USING (subscriber_id);
