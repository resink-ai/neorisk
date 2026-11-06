SELECT p.plan, c.cycle, CAST(count(*) AS BIGINT) AS invoices, CAST(sum(m.amount) AS BIGINT) AS amount
FROM an_invoices i
JOIN an_invoices_cycle c USING (invoice_id)
JOIN an_invoices_amount m USING (invoice_id)
JOIN an_invoices_for_subscriptions t USING (invoice_id)
JOIN an_subscriptions_plan p USING (subscription_id)
GROUP BY p.plan, c.cycle;
