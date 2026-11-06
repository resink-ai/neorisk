WITH started AS (
    SELECT customer, feature_1 AS plan FROM act_subscriber_stream
    WHERE activity = 'started_subscription'
)
SELECT a.feature_1 AS reason, s.plan, CAST(count(*) AS BIGINT) AS cancellations,
       CAST(avg(CAST(a.feature_2 AS BIGINT)) AS DOUBLE) AS mean_cycles_paid
FROM act_subscriber_stream a JOIN started s USING (customer)
WHERE a.activity = 'cancelled_subscription'
GROUP BY a.feature_1, s.plan;
