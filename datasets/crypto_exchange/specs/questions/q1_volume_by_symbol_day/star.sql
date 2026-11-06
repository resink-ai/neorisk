SELECT symbol, CAST(traded_at AS DATE) AS trade_date, CAST(count(*) AS BIGINT) AS trades,
       CAST(sum(qty) AS BIGINT) AS qty, CAST(sum(notional) AS BIGINT) AS notional
FROM star_fact_trades
GROUP BY symbol, trade_date;
