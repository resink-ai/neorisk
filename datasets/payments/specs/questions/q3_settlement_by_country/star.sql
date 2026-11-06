SELECT d.country, CAST(f.posted_at AS DATE) AS posted_date,
       CAST(count(*) AS BIGINT) AS settlements, CAST(sum(f.net) AS BIGINT) AS net
FROM star_fact_settlements f JOIN star_dim_merchants d USING (merchant_id)
GROUP BY d.country, CAST(f.posted_at AS DATE);
