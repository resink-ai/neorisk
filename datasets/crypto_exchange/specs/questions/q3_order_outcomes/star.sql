SELECT "type", outcome, CAST(count(*) AS BIGINT) AS orders, CAST(sum(qty) AS BIGINT) AS qty,
       CAST(sum(filled_qty) AS BIGINT) AS filled_qty
FROM star_fact_order_lifecycle
GROUP BY "type", outcome;
