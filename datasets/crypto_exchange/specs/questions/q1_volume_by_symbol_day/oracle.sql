-- Trades, quantity (lots) and notional (price * qty, in ticks) per symbol and UTC day.
SELECT symbol, CAST(event_time AS DATE) AS trade_date, CAST(count(*) AS BIGINT) AS trades,
       CAST(sum(qty) AS BIGINT) AS qty, CAST(sum(price * qty) AS BIGINT) AS notional
FROM sim.trade
GROUP BY symbol, trade_date;
