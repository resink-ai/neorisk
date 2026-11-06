-- Star schema (Kimball). A subscriber never changes plan or channel in the log, so the
-- dimension is static and facts carry the natural key. One transaction fact per business
-- event, at its grain, and one accumulating snapshot, star_fact_subscription_lifecycle: a
-- row per subscription (one per subscriber) with its milestone times, counts, amounts and
-- the status it is in at the end of the log.

-- table: star_dim_subscribers
SELECT subscriber_id, plan, signup_channel, created_at FROM subscribers;

-- table: star_fact_subscription_starts
SELECT event_id AS subscription_id, subscriber_id, plan, price, event_time AS started_at
FROM subscription_started;

-- table: star_fact_trial_conversions
SELECT subscriber_id, event_time AS converted_at FROM trial_converted;

-- table: star_fact_invoices
SELECT event_id AS invoice_id, subscriber_id, cycle, attempt, amount, event_time AS paid_at
FROM invoice_paid;

-- table: star_fact_charge_failures
SELECT event_id AS failure_id, subscriber_id, cycle, attempt, amount, reason,
       event_time AS failed_at
FROM charge_failed;

-- table: star_fact_cancellations
SELECT subscriber_id, reason, cycles_paid, event_time AS cancelled_at
FROM subscription_cancelled;

-- table: star_fact_subscription_lifecycle
-- final_status is the state the subscriber's last event (by event time, then log order)
-- leaves the subscription in: subscription_started -> trial, trial_converted -> converted
-- (first charge pending), invoice_paid -> active, charge_failed -> dunning,
-- subscription_cancelled -> cancelled.
WITH ev AS (
    SELECT subscriber_id, event_time, seq, 'trial' AS status FROM subscription_started
    UNION ALL SELECT subscriber_id, event_time, seq, 'converted' FROM trial_converted
    UNION ALL SELECT subscriber_id, event_time, seq, 'active' FROM invoice_paid
    UNION ALL SELECT subscriber_id, event_time, seq, 'dunning' FROM charge_failed
    UNION ALL SELECT subscriber_id, event_time, seq, 'cancelled' FROM subscription_cancelled
), last AS (
    SELECT subscriber_id, status AS final_status FROM ev
    QUALIFY row_number() OVER (PARTITION BY subscriber_id
                               ORDER BY event_time DESC, seq DESC) = 1
), i AS (
    SELECT subscriber_id, CAST(count(*) AS BIGINT) AS invoices_paid,
           CAST(sum(amount) AS BIGINT) AS amount_paid, max(cycle) AS last_cycle_paid,
           min(paid_at) AS first_paid_at, max(paid_at) AS last_paid_at
    FROM star_fact_invoices GROUP BY subscriber_id
), f AS (
    SELECT subscriber_id, CAST(count(*) AS BIGINT) AS charges_failed,
           CAST(sum(amount) AS BIGINT) AS amount_failed,
           min(failed_at) AS first_failed_at, max(failed_at) AS last_failed_at
    FROM star_fact_charge_failures GROUP BY subscriber_id
)
SELECT s.subscription_id, s.subscriber_id, s.plan, s.price, s.started_at, t.converted_at,
       coalesce(i.invoices_paid, 0) AS invoices_paid,
       coalesce(i.amount_paid, 0) AS amount_paid, i.last_cycle_paid,
       i.first_paid_at, i.last_paid_at,
       coalesce(f.charges_failed, 0) AS charges_failed,
       coalesce(f.amount_failed, 0) AS amount_failed,
       f.first_failed_at, f.last_failed_at,
       c.cancelled_at, c.reason AS cancel_reason, c.cycles_paid,
       l.final_status
FROM star_fact_subscription_starts s
LEFT JOIN star_fact_trial_conversions t USING (subscriber_id)
LEFT JOIN i USING (subscriber_id)
LEFT JOIN f USING (subscriber_id)
LEFT JOIN star_fact_cancellations c USING (subscriber_id)
JOIN last l USING (subscriber_id);
