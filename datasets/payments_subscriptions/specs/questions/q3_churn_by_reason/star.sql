SELECT f.reason, d.plan, CAST(count(*) AS BIGINT) AS cancellations,
       CAST(avg(f.cycles_paid) AS DOUBLE) AS mean_cycles_paid
FROM star_fact_cancellations f JOIN star_dim_subscribers d USING (subscriber_id)
GROUP BY f.reason, d.plan;
