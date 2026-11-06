WITH declined AS (
    SELECT DISTINCT md5(CAST(payment_id AS VARCHAR)) AS payment_hk
    FROM dv_sat_decline_details WHERE payment_id IS NOT NULL
), s AS (
    SELECT l.payment_hk, l.card_hk, d.amount,
           CASE WHEN l.payment_hk IN (SELECT payment_hk FROM declined) THEN 'declined'
                WHEN l.payment_hk IN (SELECT payment_hk FROM dv_sat_payments_dispute
                                      WHERE outcome = 'lost') THEN 'charged_back'
                WHEN l.payment_hk IN (SELECT r.payment_hk FROM dv_link_refund r
                                      JOIN dv_sat_refund_details x USING (refund_hk)
                                      WHERE x.outcome = 'issued') THEN 'refunded'
                WHEN l.payment_hk IN (SELECT payment_hk FROM dv_sat_payments_capture)
                    THEN 'captured'
                WHEN l.payment_hk IN (SELECT payment_hk FROM dv_sat_payments_expiry)
                    THEN 'expired'
                WHEN l.payment_hk IN (SELECT payment_hk FROM dv_sat_payments_authorization)
                    THEN 'authorized'
                ELSE 'pending' END AS final_status
    FROM dv_link_payment l JOIN dv_sat_payments_details d USING (payment_hk)
), a AS (
    SELECT s.final_status, c.brand, s.amount
    FROM s JOIN dv_sat_cards_details c USING (card_hk) WHERE s.final_status <> 'declined'
    UNION ALL
    SELECT 'declined', c.brand, x.amount
    FROM dv_link_decline k
    JOIN dv_sat_decline_details x USING (decline_hk)
    JOIN dv_link_card_customer cc USING (customer_hk)
    JOIN dv_sat_cards_details c ON c.card_hk = cc.card_hk
)
SELECT final_status, brand, CAST(count(*) AS BIGINT) AS payments,
       CAST(sum(amount) AS BIGINT) AS amount
FROM a GROUP BY final_status, brand;
