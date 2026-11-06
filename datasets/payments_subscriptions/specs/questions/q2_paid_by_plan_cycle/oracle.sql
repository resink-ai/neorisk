-- Invoices paid (count, amount) by the subscription's plan and the billing cycle.
SELECT s.plan, i.cycle, CAST(count(*) AS BIGINT) AS invoices, CAST(sum(i.amount) AS BIGINT) AS amount
FROM sim.invoice_paid i JOIN sim.subscription_started s USING (subscriber_id)
GROUP BY s.plan, i.cycle;
