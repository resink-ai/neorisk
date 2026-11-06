SELECT plan, CAST(count(*) AS BIGINT) AS subscribers, CAST(sum(price) AS BIGINT) AS price_sum
FROM star_fact_subscription_lifecycle
WHERE final_status = 'active'
GROUP BY plan;
