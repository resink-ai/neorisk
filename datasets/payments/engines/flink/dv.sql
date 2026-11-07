-- Payments Data Vault, Flink SQL port of specs/dv.sql, for `flink` and `flink-stream`.
-- Every argument of `||` is non-null (coalesced, or a hash), so Flink's `||` gives DuckDB's
-- text; integers cast to STRING print the same. The streaming planner rejects LAG over a
-- non-time ORDER BY, so each QUALIFY lag(hashdiff) IS DISTINCT FROM hashdiff becomes a
-- self-join: `ord` is (load_dts, seq) as sortable text, the previous row is the one at
-- MAX(earlier ord) of the same parent, and the row is kept when that row's hashdiff
-- differs (or there is none). Same result in both Flink modes.

-- table: dv_hub_customers
SELECT MD5(CAST(customer_id AS STRING)) AS customer_hk, customer_id, created_at AS load_dts,
       'customers_created' AS record_source
FROM customers;

-- table: dv_hub_cards
SELECT MD5(CAST(card_id AS STRING)) AS card_hk, card_id, created_at AS load_dts,
       'cards_created' AS record_source
FROM cards;

-- table: dv_hub_merchants
SELECT MD5(CAST(merchant_id AS STRING)) AS merchant_hk, merchant_id, created_at AS load_dts,
       'merchants_created' AS record_source
FROM merchants;

-- table: dv_hub_payments
SELECT MD5(CAST(payment_id AS STRING)) AS payment_hk, payment_id, created_at AS load_dts,
       'payments_created' AS record_source
FROM payments;

-- table: dv_link_card_customer
WITH k AS (SELECT MD5(CAST(card_id AS STRING)) AS card_hk,
                  MD5(CAST(customer_id AS STRING)) AS customer_hk, created_at FROM cards)
SELECT MD5(card_hk || '||' || customer_hk) AS card_customer_hk, card_hk, customer_hk,
       created_at AS load_dts, 'cards_created' AS record_source
FROM k;

-- table: dv_link_payment
WITH k AS (SELECT MD5(CAST(payment_id AS STRING)) AS payment_hk,
                  MD5(CAST(customer_id AS STRING)) AS customer_hk,
                  MD5(CAST(card_id AS STRING)) AS card_hk,
                  MD5(CAST(merchant_id AS STRING)) AS merchant_hk, created_at
           FROM payments)
SELECT MD5(payment_hk || '||' || customer_hk || '||' || card_hk || '||' || merchant_hk)
           AS payment_link_hk,
       payment_hk, customer_hk, card_hk, merchant_hk, created_at AS load_dts,
       'payments_created' AS record_source
FROM k;

-- table: dv_link_decline
WITH k AS (SELECT MD5(CAST(customer_id AS STRING)) AS customer_hk,
                  MD5(CAST(merchant_id AS STRING)) AS merchant_hk, event_id, event_time
           FROM payment_declined)
SELECT MD5(customer_hk || '||' || merchant_hk || '||' || CAST(event_id AS STRING))
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
SELECT MD5(MD5(CAST(payment_id AS STRING)) || '||' || CAST(event_id AS STRING)) AS refund_hk,
       MD5(CAST(payment_id AS STRING)) AS payment_hk, event_id AS refund_id,
       event_time AS load_dts, event_type AS record_source
FROM k;

-- table: dv_link_settlement
SELECT MD5(MD5(CAST(merchant_id AS STRING)) || '||' || CAST(event_id AS STRING))
           AS settlement_hk,
       MD5(CAST(merchant_id AS STRING)) AS merchant_hk, event_id AS settlement_id,
       event_time AS load_dts, 'settlement_posted' AS record_source
FROM settlement_posted;

-- table: dv_sat_customers_profile
SELECT MD5(CAST(customer_id AS STRING)) AS customer_hk, created_at AS load_dts,
       'customers_created' AS record_source,
       MD5(COALESCE(segment, '') || '||' || COALESCE(country, '') || '||'
           || COALESCE(CAST(credit_limit AS STRING), '')) AS hashdiff,
       segment, country, credit_limit
FROM customers;

-- table: dv_sat_customers_statement
WITH d AS (
    SELECT MD5(CAST(customer_id AS STRING)) AS customer_hk, event_time AS load_dts,
           CONCAT(DATE_FORMAT(event_time, 'yyyy-MM-dd HH:mm:ss.SSSSSS'),
                  LPAD(CAST(seq AS STRING), 20, '0')) AS ord,
           'statement_paid' AS record_source,
           MD5(COALESCE(CAST(amount AS STRING), '')) AS hashdiff, amount
    FROM statement_paid
), pk AS (
    SELECT a.customer_hk, a.ord, MAX(b.ord) AS prev_ord
    FROM d a LEFT JOIN d b ON b.customer_hk = a.customer_hk AND b.ord < a.ord
    GROUP BY a.customer_hk, a.ord
)
SELECT d.customer_hk, d.load_dts, d.record_source, d.hashdiff, d.amount
FROM d JOIN pk ON pk.customer_hk = d.customer_hk AND pk.ord = d.ord
LEFT JOIN d pr ON pr.customer_hk = pk.customer_hk AND pr.ord = pk.prev_ord
WHERE pr.hashdiff IS DISTINCT FROM d.hashdiff;

-- table: dv_sat_cards_details
SELECT MD5(CAST(card_id AS STRING)) AS card_hk, created_at AS load_dts,
       'cards_created' AS record_source, MD5(COALESCE(brand, '')) AS hashdiff, brand
FROM cards;

-- table: dv_sat_merchants_details
SELECT MD5(CAST(merchant_id AS STRING)) AS merchant_hk, created_at AS load_dts,
       'merchants_created' AS record_source,
       MD5(COALESCE(mcc, '') || '||' || COALESCE(country, '')) AS hashdiff, mcc, country
FROM merchants;

-- table: dv_sat_payments_details
SELECT MD5(CAST(payment_id AS STRING)) AS payment_hk, created_at AS load_dts,
       'payments_created' AS record_source,
       MD5(COALESCE(CAST(amount AS STRING), '')) AS hashdiff, amount
FROM payments;

-- table: dv_sat_payments_authorization
SELECT MD5(CAST(payment_id AS STRING)) AS payment_hk, event_time AS load_dts,
       'payment_authorized' AS record_source,
       MD5(COALESCE(CAST(amount AS STRING), '')) AS hashdiff, amount
FROM payment_authorized;

-- table: dv_sat_payments_capture
SELECT MD5(CAST(payment_id AS STRING)) AS payment_hk, event_time AS load_dts,
       'payment_captured' AS record_source,
       MD5(COALESCE(CAST(amount AS STRING), '') || '||'
           || COALESCE(CAST(idempotency_key AS STRING), '')) AS hashdiff,
       amount, idempotency_key
FROM payment_captured;

-- table: dv_sat_payments_replay
WITH d AS (
    SELECT MD5(CAST(payment_id AS STRING)) AS payment_hk, event_time AS load_dts,
           CONCAT(DATE_FORMAT(event_time, 'yyyy-MM-dd HH:mm:ss.SSSSSS'),
                  LPAD(CAST(seq AS STRING), 20, '0')) AS ord,
           'capture_replayed' AS record_source,
           MD5(COALESCE(CAST(idempotency_key AS STRING), '')) AS hashdiff, idempotency_key
    FROM capture_replayed
), pk AS (
    SELECT a.payment_hk, a.ord, MAX(b.ord) AS prev_ord
    FROM d a LEFT JOIN d b ON b.payment_hk = a.payment_hk AND b.ord < a.ord
    GROUP BY a.payment_hk, a.ord
)
SELECT d.payment_hk, d.load_dts, d.record_source, d.hashdiff, d.idempotency_key
FROM d JOIN pk ON pk.payment_hk = d.payment_hk AND pk.ord = d.ord
LEFT JOIN d pr ON pr.payment_hk = pk.payment_hk AND pr.ord = pk.prev_ord
WHERE pr.hashdiff IS DISTINCT FROM d.hashdiff;

-- table: dv_sat_payments_expiry
SELECT MD5(CAST(payment_id AS STRING)) AS payment_hk, event_time AS load_dts,
       'payment_expired' AS record_source,
       MD5(COALESCE(CAST(amount AS STRING), '')) AS hashdiff, amount
FROM payment_expired;

-- table: dv_sat_payments_dispute
WITH s AS (
    SELECT payment_id, event_time, seq, event_type, CAST('open' AS STRING) AS dispute_status,
           reason, CAST(NULL AS STRING) AS outcome, CAST(NULL AS BIGINT) AS chargeback
    FROM dispute_opened
    UNION ALL
    SELECT r.payment_id, r.event_time, r.seq, r.event_type, CAST('resolved' AS STRING),
           o.reason, r.outcome, r.chargeback
    FROM dispute_resolved r LEFT JOIN dispute_opened o ON o.payment_id = r.payment_id
), d AS (
    SELECT MD5(CAST(payment_id AS STRING)) AS payment_hk, event_time AS load_dts,
           CONCAT(DATE_FORMAT(event_time, 'yyyy-MM-dd HH:mm:ss.SSSSSS'),
                  LPAD(CAST(seq AS STRING), 20, '0')) AS ord,
           event_type AS record_source,
           MD5(dispute_status || '||' || COALESCE(reason, '') || '||' || COALESCE(outcome, '')
               || '||' || COALESCE(CAST(chargeback AS STRING), '')) AS hashdiff,
           dispute_status, reason, outcome, chargeback
    FROM s
), pk AS (
    SELECT a.payment_hk, a.ord, MAX(b.ord) AS prev_ord
    FROM d a LEFT JOIN d b ON b.payment_hk = a.payment_hk AND b.ord < a.ord
    GROUP BY a.payment_hk, a.ord
)
SELECT d.payment_hk, d.load_dts, d.record_source, d.hashdiff, d.dispute_status, d.reason,
       d.outcome, d.chargeback
FROM d JOIN pk ON pk.payment_hk = d.payment_hk AND pk.ord = d.ord
LEFT JOIN d pr ON pr.payment_hk = pk.payment_hk AND pr.ord = pk.prev_ord
WHERE pr.hashdiff IS DISTINCT FROM d.hashdiff;

-- table: dv_sat_decline_details
SELECT MD5(MD5(CAST(customer_id AS STRING)) || '||' || MD5(CAST(merchant_id AS STRING))
           || '||' || CAST(event_id AS STRING)) AS decline_hk,
       event_time AS load_dts, 'payment_declined' AS record_source,
       MD5(COALESCE(CAST(payment_id AS STRING), '') || '||'
           || COALESCE(CAST(amount AS STRING), '') || '||' || COALESCE(reason, '')) AS hashdiff,
       payment_id, amount, reason
FROM payment_declined;

-- table: dv_sat_refund_details
WITH k AS (
    SELECT payment_id, event_id, event_time, event_type, CAST('issued' AS STRING) AS outcome,
           amount, CAST(NULL AS STRING) AS reason
    FROM refund_issued
    UNION ALL
    SELECT payment_id, event_id, event_time, event_type, CAST('failed' AS STRING), amount,
           CAST(NULL AS STRING)
    FROM refund_failed
    UNION ALL
    SELECT payment_id, event_id, event_time, event_type, CAST('refused' AS STRING),
           CAST(NULL AS BIGINT), reason
    FROM refund_refused
)
SELECT MD5(MD5(CAST(payment_id AS STRING)) || '||' || CAST(event_id AS STRING)) AS refund_hk,
       event_time AS load_dts, event_type AS record_source,
       MD5(outcome || '||' || COALESCE(CAST(amount AS STRING), '') || '||'
           || COALESCE(reason, '')) AS hashdiff,
       outcome, amount, reason
FROM k;

-- table: dv_sat_settlement_amounts
SELECT MD5(MD5(CAST(merchant_id AS STRING)) || '||' || CAST(event_id AS STRING))
           AS settlement_hk,
       event_time AS load_dts, 'settlement_posted' AS record_source,
       MD5(COALESCE(CAST(gross AS STRING), '') || '||' || COALESCE(CAST(refunds AS STRING), '')
           || '||' || COALESCE(CAST(chargebacks AS STRING), '') || '||'
           || COALESCE(CAST(fees AS STRING), '') || '||' || COALESCE(CAST(net AS STRING), ''))
           AS hashdiff,
       gross, refunds, chargebacks, fees, net
FROM settlement_posted;
