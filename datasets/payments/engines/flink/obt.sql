-- Payments one big tables, Flink SQL port of specs/obt.sql, for `flink` and `flink-stream`.

-- table: obt_payments
WITH r AS (
    SELECT payment_id, event_time, CAST('issued' AS STRING) AS outcome, amount FROM refund_issued
    UNION ALL SELECT payment_id, event_time, CAST('failed' AS STRING), amount FROM refund_failed
    UNION ALL SELECT payment_id, event_time, CAST('refused' AS STRING), CAST(NULL AS BIGINT) FROM refund_refused
), ra AS (
    SELECT payment_id,
           CAST(sum(CASE WHEN outcome = 'issued' THEN 1 ELSE 0 END) AS BIGINT) AS refunds_issued,
           CAST(sum(CASE WHEN outcome = 'failed' THEN 1 ELSE 0 END) AS BIGINT) AS refunds_failed,
           CAST(sum(CASE WHEN outcome = 'refused' THEN 1 ELSE 0 END) AS BIGINT)
               AS refunds_refused,
           CAST(coalesce(sum(CASE WHEN outcome = 'issued' THEN amount END), 0) AS BIGINT)
               AS refunded_amount,
           min(CASE WHEN outcome = 'issued' THEN event_time END) AS first_refund_at,
           max(CASE WHEN outcome = 'issued' THEN event_time END) AS last_refund_at
    FROM r GROUP BY payment_id
), rp AS (
    SELECT payment_id, CAST(count(*) AS BIGINT) AS capture_replays
    FROM capture_replayed GROUP BY payment_id
), w AS (
    SELECT p.payment_id, p.created_at, p.amount,
           p.customer_id, cu.segment AS customer_segment, cu.country AS customer_country,
           cu.credit_limit AS customer_credit_limit,
           p.card_id, ca.brand AS card_brand,
           p.merchant_id, m.mcc AS merchant_mcc, m.country AS merchant_country,
           a.event_time AS authorized_at, d.event_time AS declined_at,
           d.reason AS decline_reason,
           c.event_time AS captured_at, coalesce(c.amount, 0) AS captured_amount,
           c.idempotency_key, coalesce(rp.capture_replays, 0) AS capture_replays,
           e.event_time AS expired_at,
           coalesce(ra.refunds_issued, 0) AS refunds_issued,
           coalesce(ra.refunds_failed, 0) AS refunds_failed,
           coalesce(ra.refunds_refused, 0) AS refunds_refused,
           coalesce(ra.refunded_amount, 0) AS refunded_amount,
           ra.first_refund_at, ra.last_refund_at,
           o.event_time AS disputed_at, o.reason AS dispute_reason,
           s.event_time AS dispute_resolved_at, s.outcome AS dispute_outcome,
           coalesce(s.chargeback, 0) AS chargeback_amount
    FROM payments p
    JOIN customers cu ON cu.customer_id = p.customer_id
    JOIN cards ca ON ca.card_id = p.card_id
    JOIN merchants m ON m.merchant_id = p.merchant_id
    LEFT JOIN payment_authorized a ON a.payment_id = p.payment_id
    LEFT JOIN payment_declined d ON d.payment_id = p.payment_id
    LEFT JOIN payment_captured c ON c.payment_id = p.payment_id
    LEFT JOIN rp ON rp.payment_id = p.payment_id
    LEFT JOIN payment_expired e ON e.payment_id = p.payment_id
    LEFT JOIN ra ON ra.payment_id = p.payment_id
    LEFT JOIN dispute_opened o ON o.payment_id = p.payment_id
    LEFT JOIN dispute_resolved s ON s.payment_id = p.payment_id
)
SELECT *,
       CASE WHEN declined_at IS NOT NULL THEN 'declined'
            WHEN dispute_outcome = 'lost' THEN 'charged_back'
            WHEN refunds_issued > 0 THEN 'refunded'
            WHEN captured_at IS NOT NULL THEN 'captured'
            WHEN expired_at IS NOT NULL THEN 'expired'
            WHEN authorized_at IS NOT NULL THEN 'authorized'
            ELSE 'pending' END AS final_status
FROM w;

-- table: obt_declines
SELECT d.event_id AS decline_id, d.payment_id, d.amount, d.reason, d.event_time AS declined_at,
       d.customer_id, cu.segment AS customer_segment, cu.country AS customer_country,
       cu.credit_limit AS customer_credit_limit,
       ca.card_id, ca.brand AS card_brand,
       d.merchant_id, m.mcc AS merchant_mcc, m.country AS merchant_country
FROM payment_declined d
JOIN customers cu ON cu.customer_id = d.customer_id
JOIN cards ca ON ca.customer_id = d.customer_id
JOIN merchants m ON m.merchant_id = d.merchant_id;

-- table: obt_settlements
SELECT s.event_id AS settlement_id, s.event_time AS posted_at,
       CAST(s.event_time AS DATE) AS posted_date, s.gross, s.refunds, s.chargebacks, s.fees,
       s.net, s.merchant_id, m.mcc AS merchant_mcc, m.country AS merchant_country
FROM settlement_posted s JOIN merchants m ON m.merchant_id = s.merchant_id;

-- table: obt_statements
SELECT st.event_id AS statement_id, st.event_time AS paid_at, st.amount, st.customer_id,
       cu.segment AS customer_segment, cu.country AS customer_country,
       cu.credit_limit AS customer_credit_limit, ca.card_id, ca.brand AS card_brand
FROM statement_paid st
JOIN customers cu ON cu.customer_id = st.customer_id
JOIN cards ca ON ca.customer_id = st.customer_id;
