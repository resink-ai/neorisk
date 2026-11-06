WITH started AS (
    SELECT customer, feature_1 AS plan FROM act_subscriber_stream
    WHERE activity = 'started_subscription'
)
SELECT s.plan, CAST(a.feature_1 AS INTEGER) AS cycle, CAST(count(*) AS BIGINT) AS invoices,
       CAST(sum(a.revenue_impact) AS BIGINT) AS amount
FROM act_subscriber_stream a JOIN started s USING (customer)
WHERE a.activity = 'paid_invoice'
GROUP BY s.plan, CAST(a.feature_1 AS INTEGER);
