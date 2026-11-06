WITH last AS (
    SELECT customer, activity FROM act_subscriber_stream
    QUALIFY row_number() OVER (PARTITION BY customer ORDER BY ts DESC, activity_id DESC) = 1
), started AS (
    SELECT customer, feature_1 AS plan, CAST(feature_2 AS BIGINT) AS price
    FROM act_subscriber_stream WHERE activity = 'started_subscription'
)
SELECT s.plan, CAST(count(*) AS BIGINT) AS subscribers, CAST(sum(s.price) AS BIGINT) AS price_sum
FROM last l JOIN started s USING (customer)
WHERE l.activity = 'paid_invoice'
GROUP BY s.plan;
