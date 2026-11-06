SELECT merchant_country AS country, posted_date,
       CAST(count(*) AS BIGINT) AS settlements, CAST(sum(net) AS BIGINT) AS net
FROM obt_settlements
GROUP BY merchant_country, posted_date;
