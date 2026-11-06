-- Star schema (Kimball). Customers, cards and merchants never change in the log, so the
-- dimensions are static and facts carry the natural keys. One transaction fact per business
-- event group, and one accumulating snapshot, star_fact_payment_lifecycle: a row per payment
-- with its milestone times, amounts and final status. A decline refused before a payment
-- exists (over_limit) has no payment_id; its card is the customer's card (one per
-- customer). The hold_* events of std.holds and credit_line_opened (it repeats the
-- customer's credit_limit) are outside the scope.

-- table: star_dim_customers
SELECT customer_id, segment, country, credit_limit, created_at FROM customers;

-- table: star_dim_cards
SELECT card_id, customer_id, brand, created_at FROM cards;

-- table: star_dim_merchants
SELECT merchant_id, mcc, country, created_at FROM merchants;

-- table: star_fact_authorizations
SELECT payment_id, customer_id, card_id, merchant_id, amount, event_time AS authorized_at
FROM payment_authorized;

-- table: star_fact_declines
SELECT d.event_id AS decline_id, d.payment_id, d.customer_id, c.card_id, d.merchant_id,
       d.amount, d.reason, d.event_time AS declined_at
FROM payment_declined d JOIN star_dim_cards c USING (customer_id);

-- table: star_fact_captures
SELECT payment_id, customer_id, merchant_id, amount, idempotency_key,
       event_time AS captured_at
FROM payment_captured;

-- table: star_fact_capture_replays
SELECT event_id AS replay_id, payment_id, customer_id, merchant_id, idempotency_key,
       event_time AS replayed_at
FROM capture_replayed;

-- table: star_fact_expirations
SELECT payment_id, customer_id, merchant_id, amount, event_time AS expired_at
FROM payment_expired;

-- table: star_fact_refunds
SELECT event_id AS refund_id, payment_id, customer_id, merchant_id, 'issued' AS outcome,
       amount, CAST(NULL AS VARCHAR) AS reason, event_time AS decided_at
FROM refund_issued
UNION ALL
SELECT event_id, payment_id, customer_id, merchant_id, 'failed', amount, NULL, event_time
FROM refund_failed
UNION ALL
SELECT event_id, payment_id, customer_id, merchant_id, 'refused', CAST(NULL AS BIGINT),
       reason, event_time
FROM refund_refused;

-- table: star_fact_disputes_opened
SELECT payment_id, customer_id, merchant_id, reason, event_time AS opened_at
FROM dispute_opened;

-- table: star_fact_disputes_resolved
SELECT payment_id, customer_id, merchant_id, outcome, chargeback, event_time AS resolved_at
FROM dispute_resolved;

-- table: star_fact_settlements
SELECT event_id AS settlement_id, merchant_id, gross, refunds, chargebacks, fees, net,
       event_time AS posted_at
FROM settlement_posted;

-- table: star_fact_statements
SELECT event_id AS statement_id, customer_id, amount, event_time AS paid_at
FROM statement_paid;

-- table: star_fact_payment_lifecycle
-- Final status by precedence: declined (refused at authorization), then charged_back (a
-- lost dispute) > refunded (any refund issued) > captured > expired > authorized; a payment
-- whose authorization is still pending at the end of the log is 'pending'.
WITH r AS (
    SELECT payment_id,
           CAST(count(*) FILTER (WHERE outcome = 'issued') AS BIGINT) AS refunds_issued,
           CAST(count(*) FILTER (WHERE outcome = 'failed') AS BIGINT) AS refunds_failed,
           CAST(count(*) FILTER (WHERE outcome = 'refused') AS BIGINT) AS refunds_refused,
           CAST(coalesce(sum(amount) FILTER (WHERE outcome = 'issued'), 0) AS BIGINT)
               AS refunded_amount,
           min(decided_at) FILTER (WHERE outcome = 'issued') AS first_refund_at,
           max(decided_at) FILTER (WHERE outcome = 'issued') AS last_refund_at
    FROM star_fact_refunds GROUP BY payment_id
), rp AS (
    SELECT payment_id, CAST(count(*) AS BIGINT) AS capture_replays
    FROM star_fact_capture_replays GROUP BY payment_id
), l AS (
    SELECT p.payment_id, p.customer_id, p.card_id, p.merchant_id, p.amount,
           p.created_at, a.authorized_at, d.declined_at, d.reason AS decline_reason,
           c.captured_at, coalesce(c.amount, 0) AS captured_amount,
           coalesce(rp.capture_replays, 0) AS capture_replays, e.expired_at,
           coalesce(r.refunds_issued, 0) AS refunds_issued,
           coalesce(r.refunds_failed, 0) AS refunds_failed,
           coalesce(r.refunds_refused, 0) AS refunds_refused,
           coalesce(r.refunded_amount, 0) AS refunded_amount,
           r.first_refund_at, r.last_refund_at,
           o.opened_at AS disputed_at, o.reason AS dispute_reason,
           s.resolved_at AS dispute_resolved_at, s.outcome AS dispute_outcome,
           coalesce(s.chargeback, 0) AS chargeback_amount
    FROM payments p
    LEFT JOIN star_fact_authorizations a USING (payment_id)
    LEFT JOIN star_fact_declines d USING (payment_id)
    LEFT JOIN star_fact_captures c USING (payment_id)
    LEFT JOIN rp USING (payment_id)
    LEFT JOIN star_fact_expirations e USING (payment_id)
    LEFT JOIN r USING (payment_id)
    LEFT JOIN star_fact_disputes_opened o USING (payment_id)
    LEFT JOIN star_fact_disputes_resolved s USING (payment_id)
)
SELECT *,
       CASE WHEN declined_at IS NOT NULL THEN 'declined'
            WHEN dispute_outcome = 'lost' THEN 'charged_back'
            WHEN refunds_issued > 0 THEN 'refunded'
            WHEN captured_at IS NOT NULL THEN 'captured'
            WHEN expired_at IS NOT NULL THEN 'expired'
            WHEN authorized_at IS NOT NULL THEN 'authorized'
            ELSE 'pending' END AS final_status
FROM l;
