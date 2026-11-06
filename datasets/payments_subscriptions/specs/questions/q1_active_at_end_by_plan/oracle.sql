-- Subscribers active at the end of the log (their last subscription event, by event time
-- then log order, is a paid invoice), and the sum of their subscription prices, by plan.
WITH ev AS (
    SELECT subscriber_id, event_time, seq, 'trial' AS status FROM sim.subscription_started
    UNION ALL SELECT subscriber_id, event_time, seq, 'converted' FROM sim.trial_converted
    UNION ALL SELECT subscriber_id, event_time, seq, 'active' FROM sim.invoice_paid
    UNION ALL SELECT subscriber_id, event_time, seq, 'dunning' FROM sim.charge_failed
    UNION ALL SELECT subscriber_id, event_time, seq, 'cancelled' FROM sim.subscription_cancelled
), last AS (
    SELECT subscriber_id, status FROM ev
    QUALIFY row_number() OVER (PARTITION BY subscriber_id
                               ORDER BY event_time DESC, seq DESC) = 1
)
SELECT s.plan, CAST(count(*) AS BIGINT) AS subscribers, CAST(sum(s.price) AS BIGINT) AS price_sum
FROM last l JOIN sim.subscription_started s USING (subscriber_id)
WHERE l.status = 'active'
GROUP BY s.plan;
