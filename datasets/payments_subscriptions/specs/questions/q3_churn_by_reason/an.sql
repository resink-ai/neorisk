SELECT r.cancel_reason AS reason, p.plan, CAST(count(*) AS BIGINT) AS cancellations,
       CAST(avg(n.cycles_paid) AS DOUBLE) AS mean_cycles_paid
FROM an_subscriptions_cancel_reason r
JOIN an_subscriptions_cycles_paid n USING (subscription_id)
JOIN an_subscriptions_plan p USING (subscription_id)
GROUP BY r.cancel_reason, p.plan;
