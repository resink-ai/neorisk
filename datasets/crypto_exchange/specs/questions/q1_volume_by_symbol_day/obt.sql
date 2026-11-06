SELECT symbol, traded_date AS trade_date, CAST(count(*) AS BIGINT) AS trades,
       CAST(sum(qty) AS BIGINT) AS qty, CAST(sum(notional) AS BIGINT) AS notional
FROM obt_trades
GROUP BY symbol, trade_date;
