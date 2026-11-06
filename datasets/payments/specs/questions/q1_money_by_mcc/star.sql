WITH e AS (
    SELECT merchant_id, 1 AS authorized, 0 AS captured, 0 AS refunded, 0 AS chargebacks
    FROM star_fact_authorizations
    UNION ALL SELECT merchant_id, 0, amount, 0, 0 FROM star_fact_captures
    UNION ALL SELECT merchant_id, 0, 0, amount, 0 FROM star_fact_refunds
              WHERE outcome = 'issued'
    UNION ALL SELECT merchant_id, 0, 0, 0, chargeback FROM star_fact_disputes_resolved
    UNION ALL SELECT DISTINCT merchant_id, 0, 0, 0, 0 FROM star_fact_payment_lifecycle
)
SELECT d.mcc, CAST(sum(e.authorized) AS BIGINT) AS authorized,
       CAST(sum(e.captured) AS BIGINT) AS captured,
       CAST(sum(e.refunded) AS BIGINT) AS refunded,
       CAST(sum(e.chargebacks) AS BIGINT) AS chargebacks
FROM e JOIN star_dim_merchants d USING (merchant_id)
GROUP BY d.mcc;
