WITH a AS (
    SELECT final_status, card_brand AS brand, amount FROM obt_payments
    WHERE final_status <> 'declined'
    UNION ALL
    SELECT 'declined', card_brand, amount FROM obt_declines
)
SELECT final_status, brand, CAST(count(*) AS BIGINT) AS payments,
       CAST(sum(amount) AS BIGINT) AS amount
FROM a GROUP BY final_status, brand;
