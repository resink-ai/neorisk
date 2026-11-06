-- Cancellations by reason and the subscription's plan, with the mean cycles paid.
SELECT c.reason, s.plan, CAST(count(*) AS BIGINT) AS cancellations,
       CAST(avg(c.cycles_paid) AS DOUBLE) AS mean_cycles_paid
FROM sim.subscription_cancelled c JOIN sim.subscription_started s USING (subscriber_id)
GROUP BY c.reason, s.plan;
