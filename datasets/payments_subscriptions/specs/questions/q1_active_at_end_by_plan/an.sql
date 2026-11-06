WITH cur AS (
    SELECT subscription_id, status FROM an_subscriptions_status
    QUALIFY row_number() OVER (PARTITION BY subscription_id ORDER BY changed_at DESC) = 1
)
SELECT p.plan, CAST(count(*) AS BIGINT) AS subscribers, CAST(sum(r.price) AS BIGINT) AS price_sum
FROM cur c
JOIN an_subscriptions_plan p USING (subscription_id)
JOIN an_subscriptions_price r USING (subscription_id)
WHERE c.status = 'active'
GROUP BY p.plan;
