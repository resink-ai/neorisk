SELECT d.region, CAST(count(*) AS BIGINT) AS orders, CAST(sum(f.amount) AS BIGINT) AS amount
FROM star_fact_orders f JOIN star_dim_users d USING (users_sk)
GROUP BY d.region;
