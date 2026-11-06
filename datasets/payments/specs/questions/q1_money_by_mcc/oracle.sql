-- Per merchant MCC: payments authorized, and the amounts captured, refunded and charged back.
WITH m AS (
    SELECT p.payment_id, mc.mcc FROM sim.payments p JOIN sim.merchants mc USING (merchant_id)
), e AS (
    SELECT payment_id, 1 AS authorized, 0 AS captured, 0 AS refunded, 0 AS chargebacks
    FROM sim.payment_authorized
    UNION ALL SELECT payment_id, 0, amount, 0, 0 FROM sim.payment_captured
    UNION ALL SELECT payment_id, 0, 0, amount, 0 FROM sim.refund_issued
    UNION ALL SELECT payment_id, 0, 0, 0, chargeback FROM sim.dispute_resolved
)
SELECT m.mcc, CAST(coalesce(sum(e.authorized), 0) AS BIGINT) AS authorized,
       CAST(coalesce(sum(e.captured), 0) AS BIGINT) AS captured,
       CAST(coalesce(sum(e.refunded), 0) AS BIGINT) AS refunded,
       CAST(coalesce(sum(e.chargebacks), 0) AS BIGINT) AS chargebacks
FROM m LEFT JOIN e USING (payment_id)
GROUP BY m.mcc;
