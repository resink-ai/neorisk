WITH a AS (
    SELECT l.final_status, c.brand, l.amount
    FROM star_fact_payment_lifecycle l JOIN star_dim_cards c USING (card_id)
    WHERE l.final_status <> 'declined'
    UNION ALL
    SELECT 'declined', c.brand, d.amount
    FROM star_fact_declines d JOIN star_dim_cards c USING (card_id)
)
SELECT final_status, brand, CAST(count(*) AS BIGINT) AS payments,
       CAST(sum(amount) AS BIGINT) AS amount
FROM a GROUP BY final_status, brand;
