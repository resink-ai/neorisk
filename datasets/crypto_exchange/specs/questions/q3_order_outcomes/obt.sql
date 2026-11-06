SELECT "type", outcome, CAST(count(*) AS BIGINT) AS orders, CAST(sum(qty) AS BIGINT) AS qty,
       CAST(sum(filled_qty) AS BIGINT) AS filled_qty
FROM obt_orders
GROUP BY "type", outcome;
