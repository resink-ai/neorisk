-- Payments by final status and card brand. Precedence: charged_back (a lost dispute) >
-- refunded (any refund issued) > captured > expired > authorized; 'pending' if the issuer has
-- not answered by the end of the log. Declines are counted separately, one per
-- payment_declined event (an over_limit decline has no payment row; its card is the
-- customer's card).
WITH s AS (
    SELECT p.payment_id, p.card_id, p.amount,
           CASE WHEN EXISTS (SELECT 1 FROM sim.payment_declined x
                             WHERE x.payment_id = p.payment_id) THEN 'declined'
                WHEN EXISTS (SELECT 1 FROM sim.dispute_resolved x
                             WHERE x.payment_id = p.payment_id AND x.outcome = 'lost')
                    THEN 'charged_back'
                WHEN EXISTS (SELECT 1 FROM sim.refund_issued x
                             WHERE x.payment_id = p.payment_id) THEN 'refunded'
                WHEN EXISTS (SELECT 1 FROM sim.payment_captured x
                             WHERE x.payment_id = p.payment_id) THEN 'captured'
                WHEN EXISTS (SELECT 1 FROM sim.payment_expired x
                             WHERE x.payment_id = p.payment_id) THEN 'expired'
                WHEN EXISTS (SELECT 1 FROM sim.payment_authorized x
                             WHERE x.payment_id = p.payment_id) THEN 'authorized'
                ELSE 'pending' END AS final_status
    FROM sim.payments p
), a AS (
    SELECT s.final_status, c.brand, s.amount
    FROM s JOIN sim.cards c USING (card_id) WHERE s.final_status <> 'declined'
    UNION ALL
    SELECT 'declined', c.brand, d.amount
    FROM sim.payment_declined d JOIN sim.cards c USING (customer_id)
)
SELECT final_status, brand, CAST(count(*) AS BIGINT) AS payments,
       CAST(sum(amount) AS BIGINT) AS amount
FROM a GROUP BY final_status, brand;
