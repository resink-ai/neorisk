SELECT d.plan, f.cycle, CAST(count(*) AS BIGINT) AS invoices, CAST(sum(f.amount) AS BIGINT) AS amount
FROM star_fact_invoices f JOIN star_dim_subscribers d USING (subscriber_id)
GROUP BY d.plan, f.cycle;
