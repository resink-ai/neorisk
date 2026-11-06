WITH e AS (
    SELECT payment_hk, 1 AS authorized, 0 AS captured, 0 AS refunded, 0 AS chargebacks
    FROM dv_sat_payments_authorization
    UNION ALL SELECT payment_hk, 0, amount, 0, 0 FROM dv_sat_payments_capture
    UNION ALL SELECT l.payment_hk, 0, 0, s.amount, 0
              FROM dv_link_refund l JOIN dv_sat_refund_details s USING (refund_hk)
              WHERE s.outcome = 'issued'
    UNION ALL SELECT payment_hk, 0, 0, 0, chargeback FROM dv_sat_payments_dispute
              WHERE dispute_status = 'resolved'
)
SELECT s.mcc, CAST(coalesce(sum(e.authorized), 0) AS BIGINT) AS authorized,
       CAST(coalesce(sum(e.captured), 0) AS BIGINT) AS captured,
       CAST(coalesce(sum(e.refunded), 0) AS BIGINT) AS refunded,
       CAST(coalesce(sum(e.chargebacks), 0) AS BIGINT) AS chargebacks
FROM dv_link_payment l
JOIN dv_sat_merchants_details s USING (merchant_hk)
LEFT JOIN e USING (payment_hk)
GROUP BY s.mcc;
