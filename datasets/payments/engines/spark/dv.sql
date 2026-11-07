-- Payments Data Vault, Spark SQL port of specs/dv.sql. Every argument of `||` is non-null
-- (coalesced, or a hash), so Spark's `||` gives DuckDB's text; integers cast to STRING print
-- the same. QUALIFY becomes a filter over a subquery with lag().

-- table: dv_hub_customers
SELECT md5(CAST(customer_id AS STRING)) AS customer_hk, customer_id, created_at AS load_dts,
       'customers_created' AS record_source
FROM customers;

-- table: dv_hub_cards
SELECT md5(CAST(card_id AS STRING)) AS card_hk, card_id, created_at AS load_dts,
       'cards_created' AS record_source
FROM cards;

-- table: dv_hub_merchants
SELECT md5(CAST(merchant_id AS STRING)) AS merchant_hk, merchant_id, created_at AS load_dts,
       'merchants_created' AS record_source
FROM merchants;

-- table: dv_hub_payments
SELECT md5(CAST(payment_id AS STRING)) AS payment_hk, payment_id, created_at AS load_dts,
       'payments_created' AS record_source
FROM payments;

-- table: dv_link_card_customer
WITH k AS (SELECT md5(CAST(card_id AS STRING)) AS card_hk,
                  md5(CAST(customer_id AS STRING)) AS customer_hk, created_at FROM cards)
SELECT md5(card_hk || '||' || customer_hk) AS card_customer_hk, card_hk, customer_hk,
       created_at AS load_dts, 'cards_created' AS record_source
FROM k;

-- table: dv_link_payment
WITH k AS (SELECT md5(CAST(payment_id AS STRING)) AS payment_hk,
                  md5(CAST(customer_id AS STRING)) AS customer_hk,
                  md5(CAST(card_id AS STRING)) AS card_hk,
                  md5(CAST(merchant_id AS STRING)) AS merchant_hk, created_at
           FROM payments)
SELECT md5(payment_hk || '||' || customer_hk || '||' || card_hk || '||' || merchant_hk)
           AS payment_link_hk,
       payment_hk, customer_hk, card_hk, merchant_hk, created_at AS load_dts,
       'payments_created' AS record_source
FROM k;

-- table: dv_link_decline
WITH k AS (SELECT md5(CAST(customer_id AS STRING)) AS customer_hk,
                  md5(CAST(merchant_id AS STRING)) AS merchant_hk, event_id, event_time
           FROM payment_declined)
SELECT md5(customer_hk || '||' || merchant_hk || '||' || CAST(event_id AS STRING))
           AS decline_hk,
       customer_hk, merchant_hk, event_id AS decline_id, event_time AS load_dts,
       'payment_declined' AS record_source
FROM k;

-- table: dv_link_refund
WITH k AS (
    SELECT payment_id, event_id, event_time, event_type FROM refund_issued
    UNION ALL
    SELECT payment_id, event_id, event_time, event_type FROM refund_failed
    UNION ALL
    SELECT payment_id, event_id, event_time, event_type FROM refund_refused
)
SELECT md5(md5(CAST(payment_id AS STRING)) || '||' || CAST(event_id AS STRING)) AS refund_hk,
       md5(CAST(payment_id AS STRING)) AS payment_hk, event_id AS refund_id,
       event_time AS load_dts, event_type AS record_source
FROM k;

-- table: dv_link_settlement
SELECT md5(md5(CAST(merchant_id AS STRING)) || '||' || CAST(event_id AS STRING))
           AS settlement_hk,
       md5(CAST(merchant_id AS STRING)) AS merchant_hk, event_id AS settlement_id,
       event_time AS load_dts, 'settlement_posted' AS record_source
FROM settlement_posted;

-- table: dv_sat_customers_profile
SELECT md5(CAST(customer_id AS STRING)) AS customer_hk, created_at AS load_dts,
       'customers_created' AS record_source,
       md5(coalesce(segment, '') || '||' || coalesce(country, '') || '||'
           || coalesce(CAST(credit_limit AS STRING), '')) AS hashdiff,
       segment, country, credit_limit
FROM customers;

-- table: dv_sat_customers_statement
WITH d AS (
    SELECT md5(CAST(customer_id AS STRING)) AS customer_hk, event_time AS load_dts, seq,
           'statement_paid' AS record_source,
           md5(coalesce(CAST(amount AS STRING), '')) AS hashdiff, amount
    FROM statement_paid
), q AS (
    SELECT *, lag(hashdiff) OVER (PARTITION BY customer_hk ORDER BY load_dts, seq) AS prev
    FROM d
)
SELECT customer_hk, load_dts, record_source, hashdiff, amount
FROM q WHERE prev IS DISTINCT FROM hashdiff;

-- table: dv_sat_cards_details
SELECT md5(CAST(card_id AS STRING)) AS card_hk, created_at AS load_dts,
       'cards_created' AS record_source, md5(coalesce(brand, '')) AS hashdiff, brand
FROM cards;

-- table: dv_sat_merchants_details
SELECT md5(CAST(merchant_id AS STRING)) AS merchant_hk, created_at AS load_dts,
       'merchants_created' AS record_source,
       md5(coalesce(mcc, '') || '||' || coalesce(country, '')) AS hashdiff, mcc, country
FROM merchants;

-- table: dv_sat_payments_details
SELECT md5(CAST(payment_id AS STRING)) AS payment_hk, created_at AS load_dts,
       'payments_created' AS record_source,
       md5(coalesce(CAST(amount AS STRING), '')) AS hashdiff, amount
FROM payments;

-- table: dv_sat_payments_authorization
SELECT md5(CAST(payment_id AS STRING)) AS payment_hk, event_time AS load_dts,
       'payment_authorized' AS record_source,
       md5(coalesce(CAST(amount AS STRING), '')) AS hashdiff, amount
FROM payment_authorized;

-- table: dv_sat_payments_capture
SELECT md5(CAST(payment_id AS STRING)) AS payment_hk, event_time AS load_dts,
       'payment_captured' AS record_source,
       md5(coalesce(CAST(amount AS STRING), '') || '||'
           || coalesce(CAST(idempotency_key AS STRING), '')) AS hashdiff,
       amount, idempotency_key
FROM payment_captured;

-- table: dv_sat_payments_replay
WITH d AS (
    SELECT md5(CAST(payment_id AS STRING)) AS payment_hk, event_time AS load_dts, seq,
           'capture_replayed' AS record_source,
           md5(coalesce(CAST(idempotency_key AS STRING), '')) AS hashdiff, idempotency_key
    FROM capture_replayed
), q AS (
    SELECT *, lag(hashdiff) OVER (PARTITION BY payment_hk ORDER BY load_dts, seq) AS prev
    FROM d
)
SELECT payment_hk, load_dts, record_source, hashdiff, idempotency_key
FROM q WHERE prev IS DISTINCT FROM hashdiff;

-- table: dv_sat_payments_expiry
SELECT md5(CAST(payment_id AS STRING)) AS payment_hk, event_time AS load_dts,
       'payment_expired' AS record_source,
       md5(coalesce(CAST(amount AS STRING), '')) AS hashdiff, amount
FROM payment_expired;

-- table: dv_sat_payments_dispute
WITH s AS (
    SELECT payment_id, event_time, seq, event_type, 'open' AS dispute_status, reason,
           CAST(NULL AS STRING) AS outcome, CAST(NULL AS BIGINT) AS chargeback
    FROM dispute_opened
    UNION ALL
    SELECT r.payment_id, r.event_time, r.seq, r.event_type, 'resolved', o.reason, r.outcome,
           r.chargeback
    FROM dispute_resolved r LEFT JOIN dispute_opened o ON o.payment_id = r.payment_id
), d AS (
    SELECT md5(CAST(payment_id AS STRING)) AS payment_hk, event_time AS load_dts, seq,
           event_type AS record_source,
           md5(dispute_status || '||' || coalesce(reason, '') || '||' || coalesce(outcome, '')
               || '||' || coalesce(CAST(chargeback AS STRING), '')) AS hashdiff,
           dispute_status, reason, outcome, chargeback
    FROM s
), q AS (
    SELECT *, lag(hashdiff) OVER (PARTITION BY payment_hk ORDER BY load_dts, seq) AS prev
    FROM d
)
SELECT payment_hk, load_dts, record_source, hashdiff, dispute_status, reason, outcome,
       chargeback
FROM q WHERE prev IS DISTINCT FROM hashdiff;

-- table: dv_sat_decline_details
SELECT md5(md5(CAST(customer_id AS STRING)) || '||' || md5(CAST(merchant_id AS STRING))
           || '||' || CAST(event_id AS STRING)) AS decline_hk,
       event_time AS load_dts, 'payment_declined' AS record_source,
       md5(coalesce(CAST(payment_id AS STRING), '') || '||'
           || coalesce(CAST(amount AS STRING), '') || '||' || coalesce(reason, '')) AS hashdiff,
       payment_id, amount, reason
FROM payment_declined;

-- table: dv_sat_refund_details
WITH k AS (
    SELECT payment_id, event_id, event_time, event_type, 'issued' AS outcome, amount,
           CAST(NULL AS STRING) AS reason
    FROM refund_issued
    UNION ALL
    SELECT payment_id, event_id, event_time, event_type, 'failed', amount, CAST(NULL AS STRING)
    FROM refund_failed
    UNION ALL
    SELECT payment_id, event_id, event_time, event_type, 'refused', CAST(NULL AS BIGINT), reason
    FROM refund_refused
)
SELECT md5(md5(CAST(payment_id AS STRING)) || '||' || CAST(event_id AS STRING)) AS refund_hk,
       event_time AS load_dts, event_type AS record_source,
       md5(outcome || '||' || coalesce(CAST(amount AS STRING), '') || '||'
           || coalesce(reason, '')) AS hashdiff,
       outcome, amount, reason
FROM k;

-- table: dv_sat_settlement_amounts
SELECT md5(md5(CAST(merchant_id AS STRING)) || '||' || CAST(event_id AS STRING))
           AS settlement_hk,
       event_time AS load_dts, 'settlement_posted' AS record_source,
       md5(coalesce(CAST(gross AS STRING), '') || '||' || coalesce(CAST(refunds AS STRING), '')
           || '||' || coalesce(CAST(chargebacks AS STRING), '') || '||'
           || coalesce(CAST(fees AS STRING), '') || '||' || coalesce(CAST(net AS STRING), ''))
           AS hashdiff,
       gross, refunds, chargebacks, fees, net
FROM settlement_posted;
