SELECT merchant_mcc AS mcc,
       CAST(count(authorized_at) AS BIGINT) AS authorized,
       CAST(sum(captured_amount) AS BIGINT) AS captured,
       CAST(sum(refunded_amount) AS BIGINT) AS refunded,
       CAST(sum(chargeback_amount) AS BIGINT) AS chargebacks
FROM obt_payments
GROUP BY merchant_mcc;
